"""Bounded private source preview from the same immutable trial archives."""
import difflib
import tarfile
from contextlib import ExitStack
from sim import tool_trial as trial

LIMITS={'changed_files':12,'source_bytes_per_file_per_arm':131072,'source_lines_per_file_per_arm':2000,
        'displayed_diff_lines':240,'displayed_diff_characters':24000}


def preview(path, expected):
    frozen=trial.verify(path,expected)
    fixtures=set((frozen.get('fixtures') or {}).get('files',{}))
    selected=sorted((set(frozen['arms']['base']['files'])|set(frozen['arms']['head']['files']))-fixtures)
    changed=[name for name in selected if frozen['arms']['base']['files'].get(name)!=frozen['arms']['head']['files'].get(name)]
    result={'contract':expected,'commits':{a:frozen['arms'][a]['commit'] for a in ('base','head')},'limits':LIMITS,
            'selected_files':len(selected),'changed_files':len(changed),'unchanged_files':len(selected)-len(changed),
            'fixtures_excluded':len(fixtures),'omitted_files':0,'omitted_source_bytes':0,'omitted_diff_lines':0,'files':[]}
    line_room=LIMITS['displayed_diff_lines'];char_room=LIMITS['displayed_diff_characters']
    with ExitStack() as stack:
        archives={a:stack.enter_context(tarfile.open(path/(a+'.tar'),mode='r:')) for a in ('base','head')}
        members={}
        for arm,archive in archives.items():
            members[arm]={}
            for member in archive:
                if member.name in members[arm] or not member.isfile() or not trial.safe_member(member.name):
                    raise ValueError('Frozen source archive contains an unsafe or duplicate member.')
                members[arm][member.name]=member
        for index,name in enumerate(changed):
            sizes={a:members[a][name].size if name in members[a] else 0 for a in archives}
            if index>=LIMITS['changed_files']:
                result['omitted_files']+=1;result['omitted_source_bytes']+=sum(sizes.values());continue
            row={'path':name,'change':'added' if name not in frozen['arms']['base']['files'] else 'removed' if name not in frozen['arms']['head']['files'] else 'modified','hashes':{a:frozen['arms'][a]['files'].get(name) for a in archives},'source_bytes':sizes,
                 'status':'shown','diff':'','omitted_diff_lines':0}
            result['files'].append(row)
            if any(n>LIMITS['source_bytes_per_file_per_arm'] for n in sizes.values()):
                row.update(status='omitted',reason='Source byte limit');result['omitted_source_bytes']+=sum(sizes.values());result['omitted_files']+=1;continue
            contents={}
            for arm,archive in archives.items():
                content=archive.extractfile(members[arm][name]).read() if name in members[arm] else b''
                if row['hashes'][arm] is not None and trial.sha256_bytes(content)!=row['hashes'][arm]:
                    raise ValueError('Source member does not match frozen file hash: '+name)
                contents[arm]=content
            try:
                if any(b'\0' in raw for raw in contents.values()):raise UnicodeError()
                lines={a:raw.decode('utf-8').splitlines(keepends=True) for a,raw in contents.items()}
            except UnicodeError:
                row.update(status='omitted',reason='Binary or non-UTF-8 source');result['omitted_source_bytes']+=sum(sizes.values());result['omitted_files']+=1;continue
            if any(len(lines[a])>LIMITS['source_lines_per_file_per_arm'] for a in lines):
                row.update(status='omitted',reason='Source line limit');result['omitted_source_bytes']+=sum(sizes.values());result['omitted_files']+=1;continue
            visible=[];truncated=False
            for line in difflib.unified_diff(lines['base'],lines['head'],fromfile='baseline/'+name,tofile='candidate/'+name,n=3):
                # A missing final newline must not visually merge separate diff records.
                rendered=line if line.endswith('\n') else line+'\n\\ No newline at end of file\n'
                count=rendered.count('\n')
                if truncated or count>line_room or len(rendered)>char_room:
                    truncated=True;row['omitted_diff_lines']+=count;continue
                visible.append(rendered);line_room-=count;char_room-=len(rendered)
            row['diff']=''.join(visible)
            if truncated:row['status']='partial'
            result['omitted_diff_lines']+=row['omitted_diff_lines']
    result['displayed_diff_lines']=LIMITS['displayed_diff_lines']-line_room
    result['displayed_diff_characters']=LIMITS['displayed_diff_characters']-char_room
    return result
