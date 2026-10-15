import sound from './sound.html?raw'
import dino from './dino.html?raw'

type HtmlTemplate = {
  id: string
  title: string
  category: string
  description: string
  html: string
}

// Each document is self-contained, with no external scripts or assets.
function document(title: string, subtitle: string, body: string, script = '', css = '') {
  return `<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title><style>
*{box-sizing:border-box}body{margin:0;background:transparent;color:#f5f7ff;font-family:system-ui,sans-serif;padding:16px}
main{max-width:600px;margin:auto;background:linear-gradient(140deg,#152a32,#182136);border:1px solid #ffffff20;border-radius:22px;padding:22px}
.brand{color:#7ce2bc;font-size:11px;letter-spacing:3px;font-weight:700}h1{font-size:25px;margin:10px 0 6px}p{color:#b7c4d4;font-size:14px;line-height:1.6}
button,input,select{font:inherit}button{border:0;border-radius:12px;background:#7ce2bc;color:#112820;padding:12px 16px;font-weight:700;cursor:pointer;min-height:44px}
button:disabled{opacity:.5;cursor:default}button:active{transform:scale(.98)}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #acafff;outline-offset:3px}
.secondary{background:#ffffff14;color:#fff}.row{display:flex;gap:10px;flex-wrap:wrap}.row>*{flex:1}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.panel{padding:16px;background:#ffffff08;border:1px solid #ffffff16;border-radius:14px;margin:14px 0}.display{text-align:center;font-size:44px;font-weight:750;letter-spacing:2px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
label{display:block;margin:12px 0 6px;color:#d0d9e6;font-size:13px}input,select{width:100%;border:1px solid #ffffff25;border-radius:10px;background:#111c2c;color:#fff;padding:11px}
.status{min-height:24px;color:#7ce2bc;font-size:13px;margin-top:14px}.hint{font-size:12px;color:#a8b5c7}.wide{width:100%}strong{color:#fff}h2{font-size:17px}
@media(max-width:360px){body{padding:8px}main{padding:16px}.display{font-size:34px}}${css}
</style></head><body><main><div class="brand">UTUSAN • INTERACTIVE</div><h1>${title}</h1><p>${subtitle}</p>${body}</main>
${script ? `<script>(()=>{${script}})();</script>` : ''}</body></html>`
}

export const htmlTemplates: HtmlTemplate[] = [
  { id: 'sound', title: 'Sound Test', category: 'Audio & game', description: 'Beep, nada rendah/tinggi, slider frekuensi, dan melodi.', html: sound },
  { id: 'dino', title: 'Dino Runner', category: 'Audio & game', description: 'Game lompat dengan skor dan rintangan.', html: dino },
  {
    id: 'quiz', title: 'Kuis interaktif', category: 'Audio & game',
    description: 'Tiga pertanyaan, umpan balik jawaban, skor akhir, dan main ulang.',
    html: document('Kuis kilat', 'Uji pengetahuanmu. Pilih satu jawaban untuk setiap pertanyaan.', `
<div class="panel"><p id="progress"></p><h2 id="question"></h2><div id="answers" class="grid"></div></div>
<div id="feedback" class="status" role="status"></div><button id="next" class="wide" hidden>Lanjut</button>`, `
const questions=[{q:'Planet terbesar di tata surya?',a:['Bumi','Jupiter','Mars','Venus'],correct:1},{q:'HTML digunakan untuk apa?',a:['Struktur halaman web','Mengisi baterai','Mengirim paket','Mengedit suara'],correct:0},{q:'Berapa hasil 12 × 8?',a:['88','108','96','84'],correct:2}];
let index=0,score=0,answered=false;const $=id=>document.getElementById(id);
function show(){answered=false;$('next').textContent=index===questions.length-1?'Lihat skor':'Lanjut';$('next').hidden=true;$('feedback').textContent='';$('progress').textContent='Pertanyaan '+(index+1)+' / '+questions.length;$('question').textContent=questions[index].q;$('answers').replaceChildren();questions[index].a.forEach((answer,i)=>{const b=document.createElement('button');b.className='secondary';b.textContent=answer;b.onclick=()=>{if(answered)return;answered=true;const correct=i===questions[index].correct;if(correct)score++;$('feedback').textContent=correct?'Benar!':'Jawaban yang benar: '+questions[index].a[questions[index].correct];[...$('answers').children].forEach(x=>x.disabled=true);$('next').hidden=false;};$('answers').append(b)});}
$('next').onclick=()=>{if(index===questions.length){index=0;score=0;show();return;}index++;if(index<questions.length){show();return;}$('question').textContent='Skor kamu: '+score+' / '+questions.length;$('progress').textContent='Kuis selesai';$('answers').replaceChildren();$('feedback').textContent='Terima kasih sudah bermain!';$('next').textContent='Main lagi';};show();`),
  },
  {
    id: 'memory', title: 'Memory Match', category: 'Audio & game',
    description: 'Cari enam pasangan kartu emoji, hitung langkah, dan mulai ulang.',
    html: document('Memory Match', 'Buka dua kartu dan temukan pasangan yang sama.', `
<div class="row hint"><span id="moves">Langkah: 0</span><span id="pairs">Pasangan: 0 / 6</span></div>
<div id="board" class="board panel"></div><button id="reset" class="wide secondary">Acak ulang</button><div id="status" class="status" role="status"></div>`, `
const $=id=>document.getElementById(id);let opened=[],matched=0,moves=0,locked=false,generation=0;
function reset(){generation++;opened=[];matched=0;moves=0;locked=false;$('moves').textContent='Langkah: 0';$('pairs').textContent='Pasangan: 0 / 6';$('status').textContent='';$('board').replaceChildren();const cards=['🌙','🌿','🎧','🚀','🍉','⭐'];const values=[...cards,...cards];for(let i=values.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[values[i],values[j]]=[values[j],values[i]];}values.forEach(value=>{const b=document.createElement('button');b.textContent='?';b.className='secondary';b.setAttribute('aria-label','Buka kartu');b.onclick=()=>{if(locked||b.disabled||opened.includes(b))return;b.textContent=value;b.setAttribute('aria-label',value);opened.push(b);if(opened.length<2)return;moves++;$('moves').textContent='Langkah: '+moves;if(opened[0].textContent===opened[1].textContent){opened.forEach(x=>x.disabled=true);opened=[];matched++;$('pairs').textContent='Pasangan: '+matched+' / 6';if(matched===6)$('status').textContent='Selesai dalam '+moves+' langkah!';}else{locked=true;const round=generation;setTimeout(()=>{if(round!==generation)return;opened.forEach(x=>{x.textContent='?';x.setAttribute('aria-label','Buka kartu')});opened=[];locked=false;},800);}};$('board').append(b)});}
$('reset').onclick=reset;reset();`, '.board{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.board button{font-size:25px;min-height:64px}'),
  },
  {
    id: 'picker', title: 'Roda pilihan', category: 'Audio & game',
    description: 'Masukkan pilihan sendiri lalu putar roda untuk memilih secara acak.',
    html: document('Mau pilih apa?', 'Tulis pilihan dipisahkan koma, lalu putar roda.', `
<label for="options">Pilihan</label><input id="options" value="Baca buku, Jalan santai, Ngoding, Dengarkan musik">
<div class="wheel-wrap"><div id="wheel"></div><div class="pointer">▼</div></div>
<button id="spin" class="wide">Putar roda</button><div id="status" class="status" role="status">Siap memilih.</div>`, `
const $=id=>document.getElementById(id);let angle=0;$('spin').onclick=()=>{const options=$('options').value.split(',').map(x=>x.trim()).filter(Boolean);if(options.length<2){$('status').textContent='Masukkan minimal dua pilihan.';return;}const pick=Math.floor(Math.random()*options.length);const palette=['#7ce2bc','#8d87ff','#ffd080','#f598af'];$('wheel').style.background='conic-gradient('+options.map((_,i)=>palette[i%palette.length]+' '+(i*360/options.length)+'deg '+((i+1)*360/options.length)+'deg').join(',')+')';const target=(360-(pick+.5)*360/options.length)%360;angle+=1440+(target-angle%360+360)%360;$('wheel').style.transform='rotate('+angle+'deg)';$('spin').disabled=true;$('options').disabled=true;$('status').textContent='Memilih…';setTimeout(()=>{$('status').textContent='Pilihan: '+options[pick];$('spin').disabled=false;$('options').disabled=false;},2500);};`, '.wheel-wrap{position:relative;width:180px;height:180px;margin:24px auto}.pointer{position:absolute;top:-12px;left:80px;color:white;font-size:28px;text-shadow:0 2px 5px #000}#wheel{width:100%;height:100%;border-radius:50%;border:6px solid #ffffff30;background:conic-gradient(#7ce2bc 0deg 90deg,#8d87ff 90deg 180deg,#ffd080 180deg 270deg,#f598af 270deg);transition:transform 2.5s cubic-bezier(.12,.65,.12,1)}'),
  },
  {
    id: 'calculator', title: 'Kalkulator', category: 'Alat bantu',
    description: 'Hitung tambah, kurang, kali, bagi, persen, dan hapus angka.',
    html: document('Kalkulator mini', 'Perhitungan praktis langsung di kartu.', `
<div id="screen" class="panel display" role="status">0</div><div id="keys" class="keys"></div>`, `
const screen=document.getElementById('screen');let value='0',saved=null,operation=null,fresh=true;
function calculate(){if(saved===null||!operation)return;const n=Number(value);const result=operation==='+'?saved+n:operation==='−'?saved-n:operation==='×'?saved*n:n===0?NaN:saved/n;value=Number.isFinite(result)?String(Number(result.toPrecision(12))):'Error';saved=null;operation=null;fresh=true;}
['C','⌫','%','÷','7','8','9','×','4','5','6','−','1','2','3','+','±','0','.','='].forEach(key=>{const b=document.createElement('button');b.textContent=key;b.className=/^[0-9.]$/.test(key)?'secondary':'';b.onclick=()=>{if(key==='C'){value='0';saved=null;operation=null;fresh=true;}else if(key==='⌫'){value=value==='Error'?'0':value.slice(0,-1)||'0';}else if(key==='±'){if(value!=='Error')value=String(-Number(value));}else if(key==='%'){if(value!=='Error')value=String(Number(value)/100);}else if(['+','−','×','÷'].includes(key)){if(operation&&!fresh)calculate();if(value!=='Error'){saved=Number(value);operation=key;fresh=true;}}else if(key==='='){calculate();}else{if(fresh||value==='Error'){value=key==='.'?'0.':key;fresh=false;}else if(value.length<15){if(key!=='.'||!value.includes('.'))value=value==='0'&&key!=='.'?key:value+key;}}screen.textContent=value;};document.getElementById('keys').append(b);});`, '.keys{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px}.keys button{font-size:20px}.display{font-size:32px;text-align:right}'),
  },
  {
    id: 'stopwatch', title: 'Stopwatch', category: 'Alat bantu',
    description: 'Mulai, jeda, reset, dan catat waktu putaran.',
    html: document('Stopwatch', 'Catat waktu dan putaran tanpa koneksi internet.', `
<div id="time" class="display panel" role="timer">00:00.00</div><div class="row"><button id="toggle">Mulai</button><button id="lap" class="secondary" disabled>Putaran</button><button id="reset" class="secondary">Reset</button></div><ol id="laps" class="hint"></ol>`, `
const $=id=>document.getElementById(id);let running=false,start=0,elapsed=0;function current(){return elapsed+(running?performance.now()-start:0);}function format(ms){const ticks=Math.floor(ms/10);return String(Math.floor(ticks/6000)).padStart(2,'0')+':'+String(Math.floor(ticks/100)%60).padStart(2,'0')+'.'+String(ticks%100).padStart(2,'0');}
$('toggle').onclick=()=>{if(running){elapsed=current();running=false;}else{start=performance.now();running=true;}$('toggle').textContent=running?'Jeda':'Lanjut';$('lap').disabled=!running;};$('lap').onclick=()=>{const li=document.createElement('li');li.textContent=format(current());$('laps').prepend(li);};$('reset').onclick=()=>{running=false;elapsed=0;$('toggle').textContent='Mulai';$('lap').disabled=true;$('laps').replaceChildren();};setInterval(()=>{$('time').textContent=format(current());},40);`),
  },
  {
    id: 'pomodoro', title: 'Timer Pomodoro', category: 'Alat bantu',
    description: 'Atur durasi fokus sendiri, mulai/jeda timer, dan reset.',
    html: document('Waktunya fokus', 'Satu pekerjaan, satu sesi. Atur durasimu sebelum mulai.', `
<label for="minutes">Durasi (menit)</label><input id="minutes" type="number" min="1" max="120" value="25">
<div id="time" class="panel display" role="timer">25:00</div><div class="row"><button id="toggle">Mulai fokus</button><button id="reset" class="secondary">Reset</button></div><div id="status" class="status" role="status">Siap untuk sesi baru.</div>`, `
const $=id=>document.getElementById(id);let remaining=1500000,deadline=0,running=false;
function render(){const seconds=Math.ceil(remaining/1000);$('time').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');}
function reset(){running=false;const minutes=Math.min(120,Math.max(1,Number($('minutes').value)||25));$('minutes').value=minutes;remaining=minutes*60000;$('minutes').disabled=false;$('toggle').textContent='Mulai fokus';$('status').textContent='Siap untuk sesi baru.';render();}
$('minutes').onchange=reset;$('reset').onclick=reset;$('toggle').onclick=()=>{if(running){remaining=Math.max(0,deadline-Date.now());running=false;$('status').textContent='Sesi dijeda.';}else{if(remaining<=0)reset();deadline=Date.now()+remaining;running=true;$('status').textContent='Fokus dulu, kamu bisa!';}$('minutes').disabled=running;$('toggle').textContent=running?'Jeda':'Lanjut';render();};setInterval(()=>{if(!running)return;remaining=Math.max(0,deadline-Date.now());render();if(!remaining){running=false;$('minutes').disabled=false;$('toggle').textContent='Mulai lagi';$('status').textContent='Sesi selesai. Saatnya istirahat!';}},250);`),
  },
  {
    id: 'catalog', title: 'Katalog produk', category: 'Kartu & informasi',
    description: 'Pilih jumlah produk dan lihat total belanja yang berubah langsung.',
    html: document('Pilihan hari ini', 'Susun pesananmu, lalu sampaikan pilihan lewat chat.', `
<div id="products"></div><div class="panel row"><strong>Total pilihan</strong><strong id="total">Rp0</strong></div>
<button id="summary" class="wide">Lihat ringkasan</button><div id="status" class="status" role="status"></div><p class="hint">Kartu ini menghitung pilihan; pesanan belum dikirim ke penjual.</p>`, `
const products=[{name:'Kopi susu',price:18000,emoji:'☕'},{name:'Matcha latte',price:22000,emoji:'🍵'},{name:'Croissant',price:16000,emoji:'🥐'}];const counts=products.map(()=>0);const money=n=>'Rp'+n.toLocaleString('id-ID');const status=document.getElementById('status');function update(){document.getElementById('total').textContent=money(products.reduce((sum,p,i)=>sum+p.price*counts[i],0));status.textContent='';}
products.forEach((p,i)=>{const card=document.createElement('div');card.className='panel';const heading=document.createElement('h2');heading.textContent=p.emoji+' '+p.name;const price=document.createElement('p');price.textContent=money(p.price);const row=document.createElement('div');row.className='row';const minus=document.createElement('button'),count=document.createElement('button'),plus=document.createElement('button');minus.textContent='−';minus.className='secondary';minus.setAttribute('aria-label','Kurangi '+p.name);plus.textContent='+';plus.setAttribute('aria-label','Tambah '+p.name);count.textContent='0';count.disabled=true;minus.onclick=()=>{counts[i]=Math.max(0,counts[i]-1);count.textContent=counts[i];update();};plus.onclick=()=>{counts[i]++;count.textContent=counts[i];update();};row.append(minus,count,plus);card.append(heading,price,row);document.getElementById('products').append(card);});document.getElementById('summary').onclick=()=>{const lines=products.flatMap((p,i)=>counts[i]?[p.name+' × '+counts[i]]:[]);status.textContent=lines.length?lines.join(' • '):'Belum ada produk dipilih.';};`),
  },
  {
    id: 'invitation', title: 'Undangan acara', category: 'Kartu & informasi',
    description: 'Kartu undangan dengan tanggal, tempat, agenda, dan pilihan kehadiran.',
    html: document('Kopi & koneksi', 'Undangan untuk teman-teman komunitas.', `
<div class="panel"><h2>Sabtu, 14 November 2026</h2><p>15.00 – 17.00 WIB<br>Ruang Komunitas, Kota Anda</p><details><summary>Lihat agenda</summary><p>15.00 · Registrasi & kopi<br>15.30 · Sharing proyek<br>16.30 · Diskusi dan kenalan</p></details></div>
<p>Apakah kamu bisa hadir?</p><div class="grid"><button id="yes">Saya hadir 🙌</button><button id="no" class="secondary">Belum bisa</button></div>
<div id="status" class="status" role="status"></div><p class="hint">Contoh undangan: ganti detail acara sebelum dikirim. Balas chat untuk menyampaikan konfirmasi.</p>`, `
document.getElementById('yes').onclick=()=>{document.getElementById('status').textContent='Pilihan: hadir. Balas chat pengundang untuk konfirmasi.';};document.getElementById('no').onclick=()=>{document.getElementById('status').textContent='Pilihan: belum bisa hadir. Sampaikan lewat chat pengundang.';};`),
  },
  {
    id: 'faq', title: 'FAQ accordion', category: 'Kartu & informasi',
    description: 'Cari pertanyaan dan buka/tutup jawaban seputar layanan.',
    html: document('Pusat bantuan', 'Cari pertanyaanmu atau ketuk untuk melihat jawabannya.', `
<label for="search">Cari pertanyaan</label><input id="search" type="search" placeholder="Pengiriman, pembayaran…">
<div id="faq"><details class="panel"><summary>Bagaimana cara memesan?</summary><p>Pilih produk, lalu kirim nama produk dan jumlahnya melalui chat.</p></details><details class="panel"><summary>Metode pembayaran apa saja?</summary><p>Contoh: transfer bank dan QRIS. Sesuaikan informasi ini dengan layanan Anda.</p></details><details class="panel"><summary>Kapan pesanan dikirim?</summary><p>Contoh: pesanan diproses dalam 1–2 hari kerja setelah pembayaran.</p></details><details class="panel"><summary>Bagaimana menghubungi bantuan?</summary><p>Balas pesan ini dengan pertanyaan dan nomor pesanan Anda.</p></details></div><div id="status" class="status" role="status"></div>`, `
document.getElementById('search').oninput=e=>{const term=e.target.value.toLowerCase();let matches=0;document.querySelectorAll('#faq details').forEach(item=>{item.hidden=!item.textContent.toLowerCase().includes(term);if(!item.hidden)matches++;});document.getElementById('status').textContent=matches?matches+' pertanyaan ditemukan.':'Tidak ada pertanyaan yang cocok.';};`, 'summary{cursor:pointer;font-weight:650;min-height:32px}'),
  },
  {
    id: 'feedback', title: 'Rating layanan', category: 'Kartu & informasi',
    description: 'Pilih 1–5 bintang, tulis komentar, dan lihat ringkasan tanggapan.',
    html: document('Bagaimana pengalamanmu?', 'Pendapatmu membantu kami memberi layanan yang lebih baik.', `
<div id="stars" class="row panel"></div><label for="comment">Komentar (opsional)</label><input id="comment" maxlength="200" placeholder="Apa yang bisa ditingkatkan?">
<button id="review" class="wide" style="margin-top:14px">Lihat tanggapan</button><div id="status" class="status" role="status"></div><p class="hint">Tanggapan ditampilkan di kartu ini. Balas chat untuk mengirimnya ke penyedia layanan.</p>`, `
let rating=0;const stars=document.getElementById('stars');for(let i=1;i<=5;i++){const b=document.createElement('button');b.textContent='☆';b.className='secondary';b.setAttribute('aria-label',i+' bintang');b.setAttribute('aria-pressed','false');b.onclick=()=>{rating=i;[...stars.children].forEach((x,index)=>{x.textContent=index<rating?'★':'☆';x.setAttribute('aria-pressed',String(index<rating));});document.getElementById('status').textContent='Rating: '+rating+' / 5';};stars.append(b);}document.getElementById('review').onclick=()=>{const comment=document.getElementById('comment').value.trim();document.getElementById('status').textContent=rating?'Tanggapan: '+rating+' / 5 bintang'+(comment?' — '+comment:''): 'Pilih rating terlebih dahulu.';};`, '#stars{padding:10px;gap:4px}#stars button{font-size:24px;padding:8px 2px}'),
  },
]
