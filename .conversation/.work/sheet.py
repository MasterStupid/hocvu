import fitz, sys
doc = fitz.open(sys.argv[1]); out = sys.argv[2]
pages = [int(x) for x in sys.argv[3].split(',')]
dpi = int(sys.argv[4]) if len(sys.argv) > 4 else 45
cols = int(sys.argv[5]) if len(sys.argv) > 5 else 4
pix = [doc[p-1].get_pixmap(dpi=dpi) for p in pages]
w, h = pix[0].width, pix[0].height
rows = (len(pix)+cols-1)//cols
canvas = fitz.Pixmap(fitz.csRGB, fitz.IRect(0,0,w*cols, h*rows), False)
canvas.clear_with(255)
for k, p in enumerate(pix):
    p.set_origin((k%cols)*w, (k//cols)*h)
    canvas.copy(p, p.irect)
canvas.save(out)
