'use strict';
async function refreshBriefings(){
  const root=document.getElementById('briefings');
  try{
    const response=await fetch('/api/world',{cache:'no-store'});
    if(!response.ok)throw Error('Feed unavailable');
    const data=await response.json(), selected=new URLSearchParams(location.search).get('server');
    root.replaceChildren();
    for(const [site,label] of [['georgia','Georgia'],['pennsylvania','Pennsylvania']]){
      if(selected&&['georgia','pennsylvania'].includes(selected)&&selected!==site)continue;
      const info=data.servers?.[site]||{}, live=info.connected===true||info.status_live===true;
      const section=document.createElement('section');section.className='intel-panel briefing-card';
      const heading=document.createElement('h2');heading.textContent=label;
      const mission=document.createElement('p');mission.textContent=live?(info.mission||'Mission name unavailable'):'Mission feed offline or stale';
      const brief=document.createElement('div');brief.className='briefing-text';
      brief.textContent=live?(info.briefing||'No general briefing is available from this server’s active mission.'):'Briefing unavailable until the mission feed reconnects.';
      section.append(heading,mission,brief);root.appendChild(section);
    }
  }catch{root.textContent='Unable to load mission briefings. Retrying automatically.';}
}
refreshBriefings();setInterval(refreshBriefings,15000);
