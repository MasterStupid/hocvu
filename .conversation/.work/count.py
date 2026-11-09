import pickle
out = pickle.load(open('/tmp/work/dump.pkl','rb'))
sections = []
cur = ('(front)', [])
for i,(k,sty,txt,img) in enumerate(out):
    if k=='P' and sty=='Heading 1':
        sections.append(cur); cur=(txt,[])
    cur[1].append((k,sty,txt,img))
sections.append(cur)
total=0
for name, blocks in sections:
    n = sum(len(t) for k,s,t,im in blocks)
    npar = sum(len(t) for k,s,t,im in blocks if k=='P')
    ntab = sum(len(t) for k,s,t,im in blocks if k=='T')
    imgs = sum(1 for k,s,t,im in blocks if im)
    tabs = sum(1 for k,s,t,im in blocks if k=='T')
    total+=n
    print(f"{name[:50]:50s} total={n:7d} para={npar:7d} tables={ntab:6d} (#tab={tabs}, #img={imgs})")
print('TOTAL', total)
