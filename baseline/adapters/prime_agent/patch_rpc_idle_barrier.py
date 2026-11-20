"""Opt-in RPC observation barrier; leaves prompts, live events and limits intact."""
from pathlib import Path
import hashlib,json,sys,re

OLD='case "get_state": {\n\t\t\t\tconst state = await connection.getState();'
NEW='''case "get_state": {
				// EvoLink-Bench requests a lifecycle barrier after agent_end. A
				// cached isStreaming=false does not settle retry/input-pump work.
				// This is an observation command, so model/tool events stay live
				// and the adapter can enforce its original work budget/cancel.
				if ((command as { trievoWaitForIdle?: boolean }).trievoWaitForIdle === true) {
					await connection.waitForIdle();
				}
				const state = await connection.getState();'''

def patch(path):
 path=Path(path);source=path.read_text(encoding='utf-8')
 if NEW in source:return {'status':'already_applied'}
 if source.count(OLD)!=1:raise ValueError('Prime RPC source changed; refuse ambiguous patch')
 updated=source.replace(OLD,NEW,1);path.write_text(updated,encoding='utf-8')
 return {'status':'applied','file':str(path),'before_sha256':hashlib.sha256(source.encode()).hexdigest(),'after_sha256':hashlib.sha256(updated.encode()).hexdigest()}

def patch_compiled(path):
 path=Path(path);source=path.read_text(encoding='utf-8')
 pattern=r'(case "get_state": \{\n)([ \t]*)(const state = await connection\.getState\(\);)(?=\n\s*const rpcState = \{)'
 marker='if (command.trievoWaitForIdle === true) await connection.waitForIdle();'
 if marker in source:return {'status':'already_applied','file':str(path)}
 matches=list(re.finditer(pattern,source))
 if not matches:raise ValueError('compiled RPC source changed; refuse ambiguous patch')
 updated=re.sub(pattern,lambda m:m[1]+m[2]+marker+'\n'+m[2]+m[3],source)
 path.write_text(updated,encoding='utf-8')
 return {'status':'applied','file':str(path),'matches':len(matches),'before_sha256':hashlib.sha256(source.encode()).hexdigest(),'after_sha256':hashlib.sha256(updated.encode()).hexdigest()}

if __name__=='__main__':print(json.dumps((patch_compiled if '--compiled' in sys.argv else patch)(sys.argv[1])))
