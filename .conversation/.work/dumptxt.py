import pickle
out = pickle.load(open('/tmp/work/dump.pkl','rb'))
with open('/tmp/work/full.txt','w') as f:
    for i,(k,sty,txt,img) in enumerate(out):
        if k=='T':
            f.write(f"[{i}] <TABLE>\n{txt}\n</TABLE>\n")
        else:
            f.write(f"[{i}] ({sty}){' [IMG]' if img else ''} {txt}\n")
