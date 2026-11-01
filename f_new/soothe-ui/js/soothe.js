/* Soothe UI behaviours. Hook your AI in via the events/methods at the bottom. */
const Soothe=(()=>{
const $=(s,r=document)=>[...r.querySelectorAll(s)];
let tEl;
function toast(msg){tEl??=Object.assign(document.body.appendChild(document.createElement('div')),{className:'s-toast',role:'status'});
 tEl.textContent=msg;tEl.classList.add('show');clearTimeout(tEl._t);tEl._t=setTimeout(()=>tEl.classList.remove('show'),2600)}
function speak(t){if('speechSynthesis' in window){speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(t);u.rate=.9;speechSynthesis.speak(u)}}
function setTranscript(text,conf=0){
 $('[data-s-said]').forEach(el=>{clearInterval(el._i);let n=0;el.textContent='';el._i=setInterval(()=>{el.textContent=text.slice(0,++n);if(n>=text.length)clearInterval(el._i)},28)});
 $('[data-s-meter]').forEach(m=>m.style.setProperty('--v',conf));
 $('[data-s-conf]').forEach(c=>c.textContent=Math.round(conf*100)+'% sure')}
function setModes(on){$('[data-mode]').forEach(m=>on.includes(m.dataset.mode)?m.setAttribute('data-on',''):m.removeAttribute('data-on'))}

// Day/night switch
$('[data-s-theme]').forEach(b=>{
 const apply=n=>{document.documentElement.dataset.theme=n?'night':'day';b.setAttribute('aria-checked',n)};
 let saved=false;try{saved=localStorage.getItem('soothe-night')==='1'}catch(e){} apply(saved);
 b.addEventListener('click',()=>{const n=b.getAttribute('aria-checked')!=='true';apply(n);try{localStorage.setItem('soothe-night',n?'1':'0')}catch(e){}})});

// Scenes: inject depth layers, parallax + glow on pointer, fireflies at night
const calm=matchMedia('(prefers-reduced-motion:reduce)').matches;
$('.s-scene').forEach(s=>{
 s.insertAdjacentHTML('afterbegin','<b style="--d:4"></b><u style="--d:8"></u><i style="--d:10"></i><i style="--d:18"></i><i style="--d:30"></i>');
 if(s.classList.contains('s-scene--night'))for(let i=0;i<16;i++)s.insertAdjacentHTML('beforeend',`<em style="left:${Math.random()*95}%;top:${35+Math.random()*55}%;animation-delay:-${Math.random()*7}s"></em>`);
 const mv=e=>{if(calm)return;const r=s.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;
  s.style.setProperty('--mx',x+'px');s.style.setProperty('--my',y+'px');
  s.style.setProperty('--px',(x/r.width-.5)*-2);s.style.setProperty('--py',(y/r.height-.5)*-2)};
 s.addEventListener('pointermove',mv);s.addEventListener('pointerdown',mv)});

// 3D tilt + glare on cards
$('.s-card').forEach(c=>{
 c.addEventListener('pointermove',e=>{if(calm)return;const r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height;
  c.classList.add('is-hot');c.style.setProperty('--ry',((x-.5)*9).toFixed(2)+'deg');c.style.setProperty('--rx',((.5-y)*9).toFixed(2)+'deg');
  c.style.setProperty('--gx',x*100+'%');c.style.setProperty('--gy',y*100+'%')});
 c.addEventListener('pointerleave',()=>{c.classList.remove('is-hot');c.style.setProperty('--rx','0deg');c.style.setProperty('--ry','0deg')})});

// Quick phrases speak aloud
$('[data-say]').forEach(b=>b.addEventListener('click',()=>{speak(b.dataset.say);toast('Speaking: '+b.dataset.say)}));

// Mood picker
$('.s-moods').forEach(g=>g.addEventListener('click',e=>{const b=e.target.closest('.s-mood');if(!b)return;
 $('.s-mood',g).forEach(x=>x.setAttribute('aria-pressed',x===b));toast('Feeling '+b.dataset.mood.toLowerCase())}));

// Feedback buttons
$('[data-s-feedback]').forEach(b=>b.addEventListener('click',()=>toast(b.dataset.sFeedback==='yes'?'Thank you. Saved.':'Got it. Let\u2019s try again.')));

// Speak orb + waveform (demo simulation: replace with real mic/camera input)
const demo=[['I would like some water, please.',.88,['lips','words']],['I am happy to see you.',.92,['expression','gesture']],['My head hurts. Can you help me?',.81,['lips','gesture','expression']]];
$('[data-s-orb]').forEach(orb=>{
 const wave=$('[data-s-wave]')[0];let bars=[],timer,seq,k=0,t=0;
 if(wave){for(let i=0;i<28;i++)wave.appendChild(document.createElement('i'));bars=[...wave.children]}
 const label=document.querySelector('[data-s-label]')||{};
 const draw=a=>bars.forEach((b,i)=>b.style.setProperty('--h',(.08+a*Math.sin((i+.5)/bars.length*Math.PI)*(.35+.65*Math.abs(Math.sin(t+i*.6)))*(.7+.3*Math.random())).toFixed(2)));
 const start=()=>{orb.classList.add('is-listening');orb.setAttribute('aria-pressed',true);label.textContent='Listening\u2026';
  setTranscript('',0);setModes([]);let m=0;const order=['lips','gesture','expression','words'];
  seq=setInterval(()=>{if(m<order.length)setModes(order.slice(0,++m))},800);
  timer=setInterval(()=>{t+=.4;draw(.9)},110);orb.dispatchEvent(new CustomEvent('s:listen-start',{bubbles:true}))};
 const stop=()=>{orb.classList.remove('is-listening');orb.setAttribute('aria-pressed',false);label.textContent='Tap to speak';
  clearInterval(timer);clearInterval(seq);draw(0);
  const ev=new CustomEvent('s:listen-stop',{bubbles:true,cancelable:true});
  if(orb.dispatchEvent(ev)){const d=demo[k++%demo.length];setModes(d[2]);setTranscript(d[0],d[1])}};
 orb.addEventListener('click',()=>orb.classList.contains('is-listening')?stop():start());draw(0)});

return{toast,speak,setTranscript,setModes}})();
