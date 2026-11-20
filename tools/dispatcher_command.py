"""Normalize repeated argparse options before a non-paying dispatcher handoff."""
def set_option(arguments: list[str], flag: str, value: str) -> list[str]:
    result=[];index=0
    while index<len(arguments):
        if arguments[index]==flag:
            if index+1==len(arguments) or arguments[index+1].startswith('--'):
                raise ValueError('malformed dispatcher option '+flag)
            index+=2
        else:
            result.append(arguments[index]);index+=1
    return result+[flag,str(value)]
