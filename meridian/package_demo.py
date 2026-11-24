"""Build an all-in-one HTML copy and two portable ZIP packages."""
from pathlib import Path
import base64,hashlib,json,re,zipfile
ROOT=Path(__file__).resolve().parent
DIST=ROOT/'dist'
s=(DIST/'index.html').read_text();css=(DIST/'style.css').read_text()
def font_uri(m):
 f=DIST/m.group(1)
 return "url(data:font/ttf;base64,"+base64.b64encode(f.read_bytes()).decode()+")"
css=re.sub(r'url\((fonts/[^)]+)\)',font_uri,css)
s=s.replace('<link rel="stylesheet" href="style.css">','<style>'+css+'</style>')
for name in ['plotly.min.js','app.js']:
 js=(DIST/name).read_text().replace('</script','<\\/script')
 s=s.replace(f'<script src="{name}"></script>','<script>'+js+'</script>')
(DIST/'meridian-standalone.html').write_text(s)
manifest={str(p.relative_to(DIST)):hashlib.sha256(p.read_bytes()).hexdigest() for p in DIST.rglob('*') if p.is_file()}
(ROOT/'data/dist-manifest.json').write_text(json.dumps(manifest,indent=2))
with zipfile.ZipFile(ROOT/'Meridian-dashboard.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in DIST.rglob('*'):
  if p.is_file():z.write(p,Path('Meridian-dashboard')/p.relative_to(DIST))
 z.write(ROOT/'README.md','Meridian-dashboard/README.md')
with zipfile.ZipFile(ROOT/'Meridian-source-and-data.zip','w',zipfile.ZIP_DEFLATED) as z:
 for path in ['build_dashboard.py','prepare_data.py','package_demo.py','requirements.txt','README.md','OPEN-DEMO.command','sql','web','dist','data/source.json','data/build-audit.json','data/model-metrics.json','data/dist-manifest.json','data/raw/online-retail-ii.zip','data/raw/world.geojson','qa/test_pipeline.py']:
  p=ROOT/path
  for f in (p.rglob('*') if p.is_dir() else [p]):
   if f.is_file():z.write(f,Path('plotline-elite-demo')/f.relative_to(ROOT))
for name in ['Meridian-dashboard.zip','Meridian-source-and-data.zip']:
 with zipfile.ZipFile(ROOT/name) as z:assert z.testzip() is None
 print(name,round((ROOT/name).stat().st_size/1024**2,1),'MB')
print('Standalone HTML:',round((DIST/'meridian-standalone.html').stat().st_size/1024**2,1),'MB')
