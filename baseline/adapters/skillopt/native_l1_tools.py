"""Expose existing Arena workspace operations through native function tools."""
import json,os,time

def tool_schemas():
    definitions=[
        ('Read','Read a UTF-8 file inside /workspace.',{'file_path':{'type':'string'}},['file_path']),
        ('Write','Write a UTF-8 file inside /workspace.',{'file_path':{'type':'string'},'content':{'type':'string'}},['file_path','content']),
        ('Edit','Replace exact text in a file inside /workspace.',{'file_path':{'type':'string'},'old_string':{'type':'string'},'new_string':{'type':'string'}},['file_path','old_string','new_string']),
        ('Bash','Run a command in the existing task workspace.',{'command':{'type':'string'}},['command']),
        ('LS','List a directory inside /workspace.',{'path':{'type':'string'}},['path']),
    ]
    return [{'type':'function','function':{'name':name,'description':desc,'parameters':{'type':'object','properties':props,'required':required,'additionalProperties':False}}} for name,desc,props,required in definitions]

def run(messages,*,chat,execute,state,max_model_calls,max_tool_calls,deadline,max_tokens,retries,timeout,reasoning_effort=None):
    messages=list(messages);executed=[];usage={};text='';reason=None
    allowed={x['function']['name'] for x in tool_schemas()}
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:reason='episode_timeout';break
        if state['model_calls']>=max_model_calls:reason='max_model_calls';break
        # The backend otherwise lets API300 override a smaller remaining Turn
        # budget. Narrow only this request and restore the transport seed.
        old=os.environ.get('TRIEVO_API_TIMEOUT_SECONDS')
        request_timeout=max(.01,min(float(timeout),remaining,float(old) if old else float(timeout)))
        if request_timeout<1:reason='episode_timeout';break
        os.environ['TRIEVO_API_TIMEOUT_SECONDS']=str(request_timeout)
        try:
            state['model_calls']+=1
            message,raw=chat(messages=messages,tools=tool_schemas(),tool_choice='auto',return_message=True,
                max_completion_tokens=max_tokens,retries=retries,stage='target_l1_native_tools',reasoning_effort=reasoning_effort,timeout=request_timeout)
        finally:
            if old is None:os.environ.pop('TRIEVO_API_TIMEOUT_SECONDS',None)
            else:os.environ['TRIEVO_API_TIMEOUT_SECONDS']=old
        for key,value in raw.items():
            if type(value) in (int,float):usage[key]=usage.get(key,0)+value
        if not isinstance(message,dict) and callable(getattr(message,'model_dump',None)):
            message=message.model_dump()
        if not isinstance(message,dict):raise ValueError('native tool reply must be a message object')
        text=str(message.get('content') or '');calls=message.get('tool_calls') or []
        if not calls:break
        assistant={**message,'role':'assistant','tool_calls':[dict(x) for x in calls]};messages.append(assistant)
        for i,call in enumerate(assistant['tool_calls']):
            if state['tool_calls']>=max_tool_calls:reason='max_tool_calls';break
            if time.monotonic()>=deadline:reason='episode_timeout';break
            state['tool_calls']+=1;function=call.get('function',{});name=function.get('name');call_id=call.get('id') or f"skillopt-native-{state['tool_calls']}";call['id']=call_id
            arguments={}
            try:
                arguments=function.get('arguments',{})
                if isinstance(arguments,str):arguments=json.loads(arguments)
                if not isinstance(arguments,dict) or name not in allowed:raise ValueError('unsupported tool or invalid arguments')
                observation=execute({'name':name,'arguments':arguments})
            except (ValueError,TypeError,OSError,KeyError) as e:observation=f'[tool error] {type(e).__name__}: {e}'
            observation=str(observation)[:24000]
            executed.append({'name':name,'arguments':arguments,'observation':observation,'tool_call_id':call_id})
            messages.append({'role':'tool','tool_call_id':call_id,'content':observation})
        if reason:break
    return {'text':text,'tool_calls':executed,'usage':usage,'limit_reason':reason}
