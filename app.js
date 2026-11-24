'use strict';
// F99th Live Operations v0.2.4-dev — dependency-free map and read-only status.
const byId = id => document.getElementById(id);
const setText = (id, value) => { byId(id).textContent = value == null ? '—' : String(value); };
const flightText = p => [p.altitude_ft == null ? 'ALT —' : `${Math.round(p.altitude_ft).toLocaleString()} ft MSL`, p.heading_deg == null ? 'HDG —' : `${Math.round(p.heading_deg % 360)}° HDG (reported)`, p.ground_speed_kt == null ? 'GS —' : `${Math.round(p.ground_speed_kt)} kt GS${p.speed_source === 'position samples' ? ' (estimated)' : ''}`].join(' · ');
const pad = n => String(n).padStart(2, '0');
const prettyTime = secs => secs == null ? '—' : `${pad(Math.floor(secs / 3600))}:${pad(Math.floor(secs % 3600 / 60))}:${pad(secs % 60)}`;
const TERRAIN_CENTERS = [
  ['afghanistan',34.15,67.85,6],['syria',34.65,37.80,6],['caucasus',42.10,43.65,6],
  ['persian',26.0,54.8,6],['sinai',29.5,33.7,6],['nevada',36.0,-115.3,7],
  ['nttr',36.0,-115.3,7],['marianas',14.7,145.5,7],['normandy',49.2,-0.65,7],
  ['channel',50.7,0.3,7],['south atlantic',-52.0,-70.2,5],['falklands',-52.0,-70.2,5],
  ['kola',68.6,28.5,6],['iraq',33.3,44.4,6],['germany',51.0,10.9,6]
];

for (const img of document.querySelectorAll('.brand-logo img,.bot-logo img')) {
  img.addEventListener('error', () => { img.hidden = true; });
  if (img.complete && img.naturalWidth === 0) img.hidden = true;
}

function health(lightId, labelId, ok, on, off) {
  const dot = byId(lightId); dot.classList.remove('up','down','warn');
  const label = byId(labelId); label.classList.remove('off','unknown');
  if (ok === true) { dot.classList.add('up'); label.textContent = on; }
  else if (ok === false) { dot.classList.add('down'); label.classList.add('off'); label.textContent = off; }
  else { dot.classList.add('warn'); label.classList.add('unknown'); label.textContent = 'Unknown'; }
}

// v0.2.4-dev — Dependency-free topographic raster map: no external JS, WebGL, or CDN.
// Small, read-only non-commercial dashboard. Browser fetches tiles directly from
 // https://tile.openmaps.fr (usage policy and attribution visible in the footer).
let TILE_HOST = 'https://tile.openmaps.fr/opentopomap/';
let activeBasemap='topo',cartoKey='',basemapChosen=false;
async function loadMapConfig(){
  try{
    const response=await fetch('/api/map-config',{cache:'no-store'});
    if(!response.ok)throw Error('Configuration unavailable');
    const config=await response.json();cartoKey=typeof config.carto_basemap_key==='string'?config.carto_basemap_key:'';
  }catch{cartoKey='';}
  for(const b of document.querySelectorAll('[data-basemap]'))if(b.dataset.basemap==='tactical'){
    b.disabled=!cartoKey;b.title=cartoKey?'CARTO Dark Matter without place labels':'CARTO basemap key is not configured';
  }
  setText('carto-status',cartoKey?'':'Tactical Dark unavailable; using Topographic.');
  if(cartoKey&&!basemapChosen)selectBasemap('tactical');
}
let redPassword=null;
const siteVisibility={georgia:true,pennsylvania:true};
for(const b of document.querySelectorAll('[data-site]'))b.addEventListener('click',()=>{const key=b.dataset.site;siteVisibility[key]=!siteVisibility[key];b.setAttribute('aria-pressed',String(siteVisibility[key]));renderPlanes();});
const visibility={blue:true,red:false,neutral:true,players:true,ai:true};
function visibleAircraft(p){return siteVisibility[p.site||'georgia'] && visibility[p.coalition] && visibility[p.is_player===false?'ai':'players'];}
for(const button of document.querySelectorAll('[data-filter]'))button.addEventListener('click',()=>{
  const key=button.dataset.filter;
  if(key==='red'&&!redPassword){byId('red-dialog').showModal();byId('red-password').focus();return;}
  visibility[key]=!visibility[key];button.setAttribute('aria-pressed',String(visibility[key]));renderPlanes();
});
function setAllAircraft(value){for(const key of Object.keys(visibility))visibility[key]=key==='red'?value&&!!redPassword:value;for(const b of document.querySelectorAll('[data-filter]'))b.setAttribute('aria-pressed',String(visibility[b.dataset.filter]));renderPlanes();}
byId('red-cancel').addEventListener('click',()=>{byId('red-password').value='';byId('red-dialog').close();});
async function unlockRed(){
  const password=byId('red-password').value;byId('red-password').value='';
  try{const response=await fetch('/api/red-access',{headers:{'X-Red-Password':password},cache:'no-store'});
    if(response.status===429){setText('red-error',`Too many attempts. Retry in ${response.headers.get('Retry-After')||60} seconds.`);return;}
    if(!response.ok){setText('red-error','Incorrect password');return;}
    redPassword=password;visibility.red=true;
    for(const b of document.querySelectorAll('[data-filter]'))if(b.dataset.filter==='red'){b.textContent='Red';b.setAttribute('aria-pressed','true');}
    setText('red-error','');byId('red-dialog').close();await refresh();
  }catch{setText('red-error','Unable to verify password');}
}
byId('red-unlock').addEventListener('click',unlockRed);
byId('red-password').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();unlockRed();}});
byId('aircraft-all').addEventListener('click',()=>setAllAircraft(true));
byId('aircraft-none').addEventListener('click',()=>setAllAircraft(false));
function selectBasemap(key){
  if(!['topo','street','dark','tactical'].includes(key))return;
  if(key==='tactical'&&!cartoKey){setText('carto-status','Tactical Dark awaits map access.');return;}
  activeBasemap=key;
  geo.setAttribute('aria-label',key==='tactical'?'CARTO Tactical Dark geographic basemap':key==='topo'?'OpenTopoMap geographic basemap':'OpenStreetMap geographic basemap');
  TILE_HOST=key==='tactical'?'https://basemaps.cartocdn.com/rastertiles/dark_nolabels/':key==='topo'?'https://tile.openmaps.fr/opentopomap/':'https://tile.openstreetmap.org/';
  geo.classList.toggle('dark-basemap',key==='dark');
  for(const b of document.querySelectorAll('[data-basemap]'))b.setAttribute('aria-pressed',String(b.dataset.basemap===key));
  hideMapError();
  byId('map-credit').replaceChildren();
  const a=document.createElement('a');a.href='https://www.openstreetmap.org/copyright';a.textContent='© OpenStreetMap contributors';a.target='_blank';a.rel='noopener';byId('map-credit').appendChild(a);
  if(key==='topo'){const t=document.createElement('a');t.href='https://github.com/sletuffe/OpenTopoMap';t.textContent=' · © OpenTopoMap-R';t.target='_blank';t.rel='noopener';byId('map-credit').appendChild(t);}
  if(key==='tactical'){const t=document.createElement('a');t.href='https://carto.com/attribution/';t.textContent=' · © CARTO';t.target='_blank';t.rel='noopener';byId('map-credit').appendChild(t);}
  renderMap();
}
for(const button of document.querySelectorAll('[data-basemap]'))button.addEventListener('click',()=>{basemapChosen=true;selectBasemap(button.dataset.basemap);});
byId('map-fallback').addEventListener('click',()=>selectBasemap('dark'));
const TILE_SIZE = 256, MAX_LAT = 85.05112878;
const clamp = (v,min,max) => Math.max(min, Math.min(max,v));
const toCoordText = p => `${Math.abs(p.lat).toFixed(2)}°${p.lat >= 0?'N':'S'} / ${Math.abs(p.lon).toFixed(2)}°${p.lon >= 0?'E':'W'}`;
let initialCenter = {lat:20,lon:0}, initialZoom=2, hasMoved=false, lastTerrain=null;
let center={...initialCenter}, zoom=initialZoom;
let mapPilots=[], mapInitialized=false, firstPositionCenter=false;
const geo=byId('geo-map');
const mapWarning=byId('tile-warning');
const mapPlaneLayer=byId('map-planes');
const terrainCanvas=document.createElement('canvas');
terrainCanvas.className='terrain-outlines';
terrainCanvas.setAttribute('aria-hidden','true');
geo.appendChild(terrainCanvas);
let terrainVisible=true;
const terrainAreas=typeof DCS_TERRAINS==='undefined'?[]:DCS_TERRAINS;
for(const area of terrainAreas){
  const option=document.createElement('option');option.value=area.id;option.textContent=area.name;
  byId('terrain-select').appendChild(option);
}
byId('terrain-toggle').addEventListener('click',()=>{
  terrainVisible=!terrainVisible;
  byId('terrain-toggle').setAttribute('aria-pressed',String(terrainVisible));
  renderTerrainOutlines();
});
byId('terrain-select').addEventListener('change',()=>{
  const area=terrainAreas.find(a=>a.id===byId('terrain-select').value);if(!area)return;
  terrainVisible=true;byId('terrain-toggle').setAttribute('aria-pressed','true');
  const points=area.ring.map(([lon,lat])=>mercatorPoint(lat,lon,0));
  const width=Math.max(...points.map(p=>p.x))-Math.min(...points.map(p=>p.x));
  const height=Math.max(...points.map(p=>p.y))-Math.min(...points.map(p=>p.y));
  const fit=Math.floor(Math.log2(Math.min(geo.clientWidth/(width*1.3),geo.clientHeight/(height*1.3))));
  setMap(area.center[1],area.center[0],fit,true);
});
const tileLayer=document.createElement('div');
tileLayer.className='raster-tile-layer';geo.appendChild(tileLayer);
let tileRedraw=0, drag=null, tileCheckTimeout=null, activeTiles=0, goodTiles=0, badTiles=0;
let mapCursor=null;
byId('map').addEventListener('pointermove',e=>{
  if(e.pointerType==='touch')return;
  mapCursor={x:e.clientX,y:e.clientY};updateCoordinates();
});
byId('map').addEventListener('pointerleave',()=>{mapCursor=null;updateCoordinates();});
function showMapError(msg){mapWarning.textContent=activeBasemap==='tactical'?'Tactical Dark tiles are unavailable. Choose the fallback below; aircraft tracking is unaffected.':msg;mapWarning.hidden=false;byId('map-fallback').hidden=activeBasemap!=='tactical';}
function hideMapError(){mapWarning.hidden=true;byId('map-fallback').hidden=true;}
function tileUrl(z,x,y){return `${TILE_HOST}${z}/${x}/${y}.png${activeBasemap==='tactical'?'?key='+encodeURIComponent(cartoKey):''}`;}
function mercatorPoint(lat,lon,z){
  const scale=TILE_SIZE*Math.pow(2,z), rad=clamp(lat,-MAX_LAT,MAX_LAT)*Math.PI/180;
  return {x:(lon+180)/360*scale,y:(1-Math.log(Math.tan(rad)+1/Math.cos(rad))/Math.PI)*scale/2};
}
function worldToCoord(x,y,z){
  const scale=TILE_SIZE*Math.pow(2,z);
  return {lat:(180/Math.PI)*Math.atan(Math.sinh(Math.PI*(1-2*y/scale))),lon:((x/scale)*360-180+540)%360-180};
}
function pointOnScreen(lat,lon){
  const p=mercatorPoint(lat,lon,zoom),m=mercatorPoint(center.lat,center.lon,zoom),size=TILE_SIZE*Math.pow(2,zoom);
  let dx=p.x-m.x;if(dx>size/2)dx-=size;if(dx< -size/2)dx+=size;
  return {x:geo.clientWidth/2+dx,y:geo.clientHeight/2+p.y-m.y};
}
function updateCoordinates(){
  if(!mapCursor){setText('map-coordinate','Move cursor over map');setText('map-dms','—');setText('map-mgrs','—');return;}
  const rect=geo.getBoundingClientRect(),x=mapCursor.x-rect.left,y=mapCursor.y-rect.top;
  if(x<0||y<0||x>rect.width||y>rect.height){setText('map-coordinate','Move cursor over map');setText('map-dms','—');setText('map-mgrs','—');return;}
  const origin=mercatorPoint(center.lat,center.lon,zoom);
  const position=worldToCoord(origin.x+x-rect.width/2-(drag?.dx||0),origin.y+y-rect.height/2-(drag?.dy||0),zoom);
  const formats=cursorFormats(position.lat,position.lon);
  setText('map-coordinate',formats.ddm);setText('map-dms',formats.dms);setText('map-mgrs',formats.mgrs);
}
function placeTerrainLabels(candidates,w,h,reserved=[]){
  const boxes=reserved.map(b=>({...b})),placed=[];
  const overlaps=(a,b)=>a.left<b.right+4&&a.right>b.left-4&&a.top<b.bottom+4&&a.bottom>b.top-4;
  for(const label of [...candidates].sort((a,b)=>a.top-b.top||a.name.localeCompare(b.name))){
    let chosen=null;
    // Every candidate is above its area's northern edge. Never draw an unresolved collision.
    for(let y=Math.min(h-14,label.top-18);y>=14&&!chosen;y-=25){
      const preferred=clamp(label.anchorX,label.width/2+4,w-label.width/2-4);
      const xs=[preferred];
      for(let delta=25;delta<w;delta+=25)xs.push(preferred-delta,preferred+delta);
      for(const x of xs){
        const box={left:x-label.width/2,right:x+label.width/2,top:y-10,bottom:y+11};
        if(box.left<4||box.right>w-4||boxes.some(b=>overlaps(box,b)))continue;
        chosen={...label,x,y};boxes.push(box);break;
      }
    }
    if(chosen)placed.push(chosen);
  }
  return placed;
}
function renderTerrainOutlines(){
  terrainCanvas.hidden=!terrainVisible;
  if(!terrainVisible)setText('terrain-label-note','');
  const ctx=terrainCanvas.getContext?.('2d');if(!ctx||!terrainVisible)return;
  const w=geo.clientWidth,h=geo.clientHeight,ratio=window.devicePixelRatio||1;
  terrainCanvas.width=Math.round(w*ratio);terrainCanvas.height=Math.round(h*ratio);
  terrainCanvas.style.width=w+'px';terrainCanvas.style.height=h+'px';
  ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);
  const scale=TILE_SIZE*2**zoom,m=mercatorPoint(center.lat,center.lon,zoom),labels=[];
  for(const area of terrainAreas){
    const origin=mercatorPoint(area.center[1],area.center[0],zoom);
    const shift=Math.round((m.x-origin.x)/scale)*scale;
    const points=area.ring.map(([lon,lat])=>{const p=mercatorPoint(lat,lon,zoom);return {x:w/2+p.x+shift-m.x,y:h/2+p.y-m.y};});
    for(const offset of [-scale,0,scale]){
      if(Math.max(...points.map(p=>p.x+offset))<0||Math.min(...points.map(p=>p.x+offset))>w||Math.max(...points.map(p=>p.y))<0||Math.min(...points.map(p=>p.y))>h)continue;
      ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x+offset,p.y):ctx.moveTo(p.x+offset,p.y));ctx.closePath();
      ctx.fillStyle='#56dcff0a';ctx.fill();ctx.setLineDash([7,4]);ctx.lineWidth=2;ctx.strokeStyle='#69e0ff';ctx.stroke();ctx.setLineDash([]);
      const top=Math.min(...points.map(p=>p.y));
      const anchorX=(Math.min(...points.map(p=>p.x))+Math.max(...points.map(p=>p.x)))/2+offset;
      ctx.font='bold 12px sans-serif';const tw=ctx.measureText(area.name).width+12;
      labels.push({width:tw,name:area.name,anchorX,top});
    }
  }
  const reserved=[];
  if(geo.getBoundingClientRect){
    const mapRect=geo.getBoundingClientRect();
    for(const element of document.querySelectorAll('.map-overlay-head,.map-controls,.map-overlay-bottom,.osm-credit')){
      const r=element.getBoundingClientRect();
      reserved.push({left:r.left-mapRect.left,right:r.right-mapRect.left,top:r.top-mapRect.top,bottom:r.bottom-mapRect.top});
    }
  }
  const placed=placeTerrainLabels(labels,w,h,reserved);
  setText('terrain-label-note',placed.length<labels.length?'Zoom or pan to reveal more terrain names.':'');
  for(const label of placed){
    const {x,y,width,name,anchorX,top}=label;
    if(top>0&&top<h){ctx.beginPath();ctx.moveTo(x,y+11);ctx.lineTo(anchorX,top);ctx.strokeStyle='#69e0ff99';ctx.lineWidth=1;ctx.stroke();}
    ctx.fillStyle='#071929ef';ctx.fillRect(x-width/2,y-10,width,21);
    ctx.font='bold 12px sans-serif';ctx.fillStyle='#b7f3ff';ctx.textAlign='center';ctx.fillText(name,x,y+5);
  }
}
function renderPlanes(){
  const positioned=mapPilots.filter(p=>p.lat!=null&&p.lon!=null&&Number.isFinite(p.lat)&&Number.isFinite(p.lon));
  const shown=positioned.filter(visibleAircraft).length;
  setText('map-data-label', `${shown} / ${positioned.length} aircraft visible`);
  mapPlaneLayer.replaceChildren();
  for(const p of mapPilots){
    if(!visibleAircraft(p))continue;
    if(p.lat==null||p.lon==null||!Number.isFinite(p.lat)||!Number.isFinite(p.lon))continue;
    const where=pointOnScreen(p.lat,p.lon);
    if(where.x< -110||where.x>geo.clientWidth+110||where.y< -55||where.y>geo.clientHeight+55)continue;
    const pin=document.createElement('div');pin.className='plane-pin '+p.coalition+(p.site==='pennsylvania'?' pennsylvania':'');
    const name=document.createElement('span');name.textContent=(p.site==='pennsylvania'?'PA · ':'GA · ')+(p.callsign||'Pilot');
    const aircraft=document.createElement('small');aircraft.textContent=p.aircraft||'Aircraft';
    const arrow=document.createElement('span');arrow.className='heading-arrow';arrow.textContent=p.heading_deg==null?'•':'↑';
    if(p.heading_deg!=null)arrow.style.transform=`rotate(${p.heading_deg}deg)`;
    pin.append(arrow,name,aircraft);pin.style.left=where.x+'px';pin.style.top=where.y+'px';
    pin.title=`${p.callsign||'Pilot'} · ${p.aircraft||'Aircraft'} · ${p.altitude_ft==null?'altitude unknown':Math.round(p.altitude_ft).toLocaleString()+' ft'}`;
    pin.title += ' · ' + flightText(p) + (p.is_player===false?' · AI':' · Player');
    mapPlaneLayer.appendChild(pin);
  }
}
function renderMap(){
  const w=geo.clientWidth,h=geo.clientHeight;
  if(w<10||h<10)return;
  const m=mercatorPoint(center.lat,center.lon,zoom),left=m.x-w/2,top=m.y-h/2;
  const firstX=Math.floor(left/TILE_SIZE),lastX=Math.floor((left+w)/TILE_SIZE);
  const firstY=Math.floor(top/TILE_SIZE),lastY=Math.floor((top+h)/TILE_SIZE);
  const maxIndex=Math.pow(2,zoom),fragment=document.createDocumentFragment();
  activeTiles=0;goodTiles=0;badTiles=0;
  const current=++tileRedraw;
  if(tileCheckTimeout)clearTimeout(tileCheckTimeout);
  for(let y=firstY;y<=lastY;y++){
    if(y<0||y>=maxIndex)continue;
    for(let x=firstX;x<=lastX;x++){
      if(activeTiles>=70)break;
      const wrapped=((x%maxIndex)+maxIndex)%maxIndex;
      const img=document.createElement('img');
      img.className='map-raster-tile';img.alt='';img.draggable=false;
      img.style.left=Math.round(x*TILE_SIZE-left)+'px';
      img.style.top=Math.round(y*TILE_SIZE-top)+'px';
      img.width=TILE_SIZE;img.height=TILE_SIZE;
      img.addEventListener('load',()=>{if(current!==tileRedraw)return;goodTiles++;if(goodTiles>0&&badTiles===0)hideMapError();});
      img.addEventListener('error',()=>{if(current!==tileRedraw)return;badTiles++;if(activeBasemap==='tactical'||goodTiles===0&&badTiles>=activeTiles)showMapError('The selected map tile host is not responding. Your DCS telemetry remains available.');});
      img.src=tileUrl(zoom,wrapped,y);
      fragment.appendChild(img);activeTiles++;
    }
  }
  tileLayer.replaceChildren(fragment);
  if(activeTiles===0)showMapError('Map tiles unavailable at this location.');
  else tileCheckTimeout=setTimeout(()=>{if(current===tileRedraw&&goodTiles===0)showMapError('The geographic basemap has not loaded. Try another basemap; status data is unaffected.');},10000);
  updateCoordinates();renderTerrainOutlines();renderPlanes();
}
function setMap(lat,lon,z,manual=false){
  if(manual)hasMoved=true;
  center={lat:clamp(lat,-MAX_LAT,MAX_LAT),lon:((lon+540)%360)-180};zoom=clamp(Math.round(z),2,11);
  renderMap();
}
function zoomBy(d){setMap(center.lat,center.lon,zoom+d,true);}
byId('zoom-in').addEventListener('click',()=>zoomBy(1));
byId('zoom-out').addEventListener('click',()=>zoomBy(-1));
byId('map-home').addEventListener('click',()=>{hasMoved=false;setMap(initialCenter.lat,initialCenter.lon,initialZoom);});
byId('map').addEventListener('keydown',e=>{
  if(e.target!==byId('map'))return;
  const directions={ArrowLeft:[-80,0],ArrowRight:[80,0],ArrowUp:[0,-80],ArrowDown:[0,80]};
  if(directions[e.key]){
    e.preventDefault();const p=mercatorPoint(center.lat,center.lon,zoom),d=directions[e.key];
    const next=worldToCoord(p.x+d[0],p.y+d[1],zoom);setMap(next.lat,next.lon,zoom,true);
  }else if(['+','=','-','Home'].includes(e.key)){
    e.preventDefault();if(e.key==='Home'){hasMoved=false;setMap(initialCenter.lat,initialCenter.lon,initialZoom);}
    else zoomBy(e.key==='-'?-1:1);
  }
});
geo.addEventListener('wheel',e=>{e.preventDefault();zoomBy(e.deltaY<0?1:-1);},{passive:false});
geo.addEventListener('pointerdown',e=>{
  if(e.button!==0||e.target.closest('a,button'))return;
  drag={id:e.pointerId,x:e.clientX,y:e.clientY,dx:0,dy:0};
  geo.setPointerCapture(e.pointerId);
});
geo.addEventListener('pointermove',e=>{
  if(!drag||drag.id!==e.pointerId)return;
  drag.dx=e.clientX-drag.x;drag.dy=e.clientY-drag.y;
  tileLayer.style.transform=`translate(${drag.dx}px,${drag.dy}px)`;
  mapPlaneLayer.style.transform=tileLayer.style.transform;
  terrainCanvas.style.transform=tileLayer.style.transform;
});
function finishDrag(e){
  if(!drag||drag.id!==e.pointerId)return;
  const {dx,dy}=drag;drag=null;
  tileLayer.style.transform='';mapPlaneLayer.style.transform='';terrainCanvas.style.transform='';
  if(Math.abs(dx)+Math.abs(dy)>3){
    const p=mercatorPoint(center.lat,center.lon,zoom);
    const next=worldToCoord(p.x-dx,p.y-dy,zoom);
    setMap(next.lat,next.lon,zoom,true);
  }
}
geo.addEventListener('pointerup',finishDrag);
geo.addEventListener('pointercancel',finishDrag);
window.addEventListener('resize',()=>renderMap());
function updateMapTerrain(raw){
  if(!raw)return;
  const normalized=String(raw).toLowerCase();
  if(normalized===lastTerrain)return;
  lastTerrain=normalized;
  const loc=TERRAIN_CENTERS.find(([key])=>normalized.includes(key));
  if(loc){initialCenter={lat:loc[1],lon:loc[2]};initialZoom=loc[3];if(!hasMoved)setMap(initialCenter.lat,initialCenter.lon,initialZoom);}
}
let fittedSites='';
function requestDraw(){
  const valid=mapPilots.filter(p=>visibleAircraft(p)&&Number.isFinite(p.lat)&&Number.isFinite(p.lon));
  const sites=[...new Set(valid.map(p=>p.site||'georgia'))].sort().join('|');
  if(valid.length&&!hasMoved&&sites!==fittedSites){
    fittedSites=sites;
    const lons=valid.map(p=>(p.lon+360)%360).sort((a,b)=>a-b);
    let gap=-1,start=0;
    for(let i=0;i<lons.length;i++){const next=i+1<lons.length?lons[i+1]:lons[0]+360;if(next-lons[i]>gap){gap=next-lons[i];start=next%360;}}
    const span=360-gap, longitude=(start+span/2+540)%360-180;
    const ys=valid.map(p=>mercatorPoint(p.lat,p.lon,0).y);
    const minY=Math.min(...ys),maxY=Math.max(...ys);
    const latitude=worldToCoord(0,(minY+maxY)/2,0).lat;
    const scaleX=Math.max(1,geo.clientWidth-180)/Math.max(1,span/360*256);
    const scaleY=Math.max(1,geo.clientHeight-140)/Math.max(1,maxY-minY);
    initialCenter={lat:latitude,lon:longitude};initialZoom=clamp(Math.floor(Math.log2(Math.min(scaleX,scaleY))),2,8);
    setMap(latitude,longitude,initialZoom);return;
  }
  renderPlanes();
}
renderMap(); // Independent of /api/status and any external script.

function populateRoster(feed) {
  const roster=byId('roster');roster.replaceChildren();
  if(!feed?.connected){
    const p=document.createElement('p');p.className='empty-roster';
    p.textContent='Pilot count can come from the mission feed; individual aircraft and positions require a separate verified roster feed.';
    roster.appendChild(p);setText('roster-count','—');
    setText('roster-note','No pilot-position telemetry supplied yet');mapPilots=[];requestDraw();return;
  }
  const pilots=Array.isArray(feed.pilots)?feed.pilots:[];
  const age=value=>Number.isFinite(value)?`${value}s old`:'offline';
  const ages=feed.site_ages;
  setText('roster-count',pilots.length);setText('roster-note',ages?`${pilots.length} pilots · Georgia: ${age(ages.georgia)} · Pennsylvania: ${age(ages.pennsylvania)}`:`${pilots.length} pilots · ${Number.isFinite(feed.age_seconds)?age(feed.age_seconds):'Feed age unavailable'}`);
  if(pilots.length===0){const p=document.createElement('p');p.className='empty-roster';p.textContent='No individual pilots currently reported.';roster.appendChild(p);}
  for(const p of pilots){
    const row=document.createElement('div');row.className='roster-row '+p.coalition;
    const info=document.createElement('div'), name=document.createElement('strong'), aircraft=document.createElement('div');
    name.textContent=(p.site==='pennsylvania'?'PA · ':'GA · ')+(p.callsign||'Pilot');
    if(Number.isFinite(p.lat)&&Number.isFinite(p.lon)){
      name.setAttribute('role','button');name.setAttribute('tabindex','0');name.className='pilot-location';
      name.setAttribute('title','Center map on '+(p.callsign||'pilot'));
      const focusPilot=()=>setMap(p.lat,p.lon,Math.max(zoom,8),true);
      name.addEventListener('click',focusPilot);
      name.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focusPilot();}});
    }
    aircraft.textContent=p.aircraft||'Aircraft not reported';aircraft.style.fontSize='10px';aircraft.style.color='#91a8c1';const details=document.createElement('small');details.className='flight-details';details.textContent=flightText(p);info.append(name,aircraft,details);
    const side=document.createElement('span');side.textContent=p.coalition.toUpperCase();row.append(info,side);roster.appendChild(row);
  }
  mapPilots=pilots;requestDraw();
}
async function refresh() {
  try {
    let response=await fetch('/api/world',{cache:'no-store',headers:redPassword?{'X-Red-Password':redPassword}:{}});
    if(response.status===429&&redPassword){
      redPassword=null;visibility.red=false;
      for(const b of document.querySelectorAll('[data-filter]'))if(b.dataset.filter==='red'){b.textContent='Red 🔒';b.setAttribute('aria-pressed','false');}
      setText('red-error','Red access is temporarily rate limited. Try again shortly.');
      response=await fetch('/api/world',{cache:'no-store'});
    }
    if(!response.ok)throw Error(`HTTP ${response.status}`);
    const obj=await response.json(), c=obj.checks||{}, t=obj.telemetry||{};
    byId('connection-light').className='light up';setText('connection-state','CONNECTED');
    renderServers(obj.servers||{});
    const pa=obj.servers?.pennsylvania||{};
    const f=obj.roster||{connected:false,pilots:[]};
    populateRoster(f);
    if(obj.aircraft?.connected){mapPilots=obj.aircraft.aircraft;requestDraw();setText('aircraft-scope',`${mapPilots.length} aircraft from connected sites`);}
    else{setText('aircraft-scope','Player feed only • full mission feed pending');}
    const posCount=mapPilots.filter(p=>p.lat!=null&&p.lon!=null).length;

    setText('map-signal',posCount>0?`${posCount} live aircraft positions`:t.connected?'Mission feed connected • positions pending':'Awaiting mission telemetry');
    setText('map-updated',`GA: ${t.connected?t.age_seconds+'s':'offline'} · PA: ${pa.live?pa.age_seconds+'s':'offline'}`);
    setText('map-data-footer',posCount>0?'Aircraft tracked from recent telemetry':'Aircraft positions require a verified feed');
    setText('map-source-footer',posCount>0?'Read-only aircraft-position telemetry': 'Aircraft positions require a trusted feed');
    setText('last-check','Last checked '+new Date().toLocaleTimeString());
  } catch(err) {
    byId('connection-light').className='light down';setText('connection-state','DASHBOARD DISCONNECTED');
    setText('last-check','Unable to reach /api/status');
    populateRoster({connected:false,pilots:[]});
    setText('map-signal','Dashboard disconnected • positions cleared');renderServers({});
  }
}
let clockAnchor=null;
async function syncClock(){
  try{const response=await fetch('/api/clock',{cache:'no-store'});const c=await response.json();
    clockAnchor=c.synced&&Number.isFinite(c.utc_ms)?{utc:c.utc_ms,local:performance.now()}:null;
  }catch{clockAnchor=null;}
  updateClock();
}
function updateClock(){
  if(!clockAnchor||performance.now()-clockAnchor.local>900000){setText('clock','ET • sync unavailable');return;}
  setText('clock',new Date(clockAnchor.utc+performance.now()-clockAnchor.local).toLocaleTimeString('en-US',{timeZone:'America/New_York',hour12:false,timeZoneName:'short'}));
}
updateClock();syncClock();loadMapConfig();setInterval(syncClock,60000);setInterval(updateClock,1000);refresh();setInterval(refresh,5000);

function renderServers(servers){
  const dcs=byId('dcs-details'), srs=byId('srs-details');
  dcs.replaceChildren();srs.replaceChildren();
  for(const [site,label] of [['georgia','Georgia'],['pennsylvania','Pennsylvania']]){
    const data=servers[site]||{}, live=data.connected===true||data.status_live===true;
    const details=data.services||{}, conditions=data.conditions||{};
    const age=data.status_age_seconds??data.age_seconds;
    setText(site+'-feed',live?`LIVE / ${age??'?'}s`:'Offline / stale');
    for(const [key,value] of Object.entries({mission:data.mission,terrain:data.terrain,state:data.mission_state,weather:conditions.weather,elapsed:prettyTime(data.mission_elapsed_seconds),count:data.pilot_count??data.connected_players})){
      setText(site+'-'+key,live?(value??'Not reported'):'Unavailable');
    }
    const seconds=conditions.time_seconds;
    setText(site+'-clock',live&&Number.isFinite(seconds)?`${seconds>=21600&&seconds<64800?'☀':'☾'} ${prettyTime(Math.floor(seconds))}`:'Not reported');
    byId(site+'-clock').title='Mission local time; day/night estimated using 06:00–18:00 daylight.';
    const row=document.createElement('div');row.className='service-row';
    row.textContent=`${label} · ${live?(data.mission_state||'Mission online'):'Status unavailable'} · DCS ${details.dcs_version||'version unavailable'}`;
    dcs.appendChild(row);
    const radio=document.createElement('div');radio.className='service-row';
    radio.textContent=`${label} · SRS ${details.srs_version||'version unavailable'} · ${details.srs_listening===true?'Listening':details.srs_listening===false?'Not listening':'Listening status unavailable'} · Port ${details.srs_port??'unavailable'} · ${details.srs_address||'Address unavailable'}`;
    srs.appendChild(radio);
  }
}

async function refreshReleaseVersions(){
  try{
    const response=await fetch('/api/releases',{cache:'no-store'});
    if(!response.ok)throw Error('Release check unavailable');
    const releases=await response.json();
    for(const key of ['dcs','srs']){
      const release=releases[key]||{};
      setText(key+'-latest',release.version?`Latest: ${release.version}${release.stale?' (last known)':''}`:'Latest: unavailable');
      byId(key+'-latest').title=release.checked_at?`Publisher release checked ${new Date(release.checked_at).toLocaleString()}${release.stale?'; refresh unavailable':''}`:'Publisher release check unavailable';
    }
  }catch{for(const key of ['dcs','srs'])setText(key+'-latest','Latest: unavailable');}
}
refreshReleaseVersions();setInterval(refreshReleaseVersions,60000);
