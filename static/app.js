(function () {
  var $ = function (s) { return document.querySelector(s); };
  var audio = $('#audio'), grid = $('#grid'), tracks = [], cur = -1, curId = null;
  var video = document.createElement('video');
  video.className = 'gallery-video';
  video.controls = true;
  video.playsInline = true;
  video.preload = 'metadata';
  video.hidden = true;
  grid.parentNode.insertBefore(video, grid);
  var tokens = {};
  try { tokens = JSON.parse(localStorage.getItem('mg_tokens') || '{}'); } catch (e) {}
  function saveTokens() { try { localStorage.setItem('mg_tokens', JSON.stringify(tokens)); } catch (e) {} }

  function toast(msg) {
    var t = $('#toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(toast.h); toast.h = setTimeout(function () { t.classList.remove('show'); }, 2600);
  }
  function fmtTime(s) { if (!isFinite(s)) return '0:00'; s = Math.floor(s); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function fmtSize(n) { return n < 1048576 ? (n / 1024).toFixed(0) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
  function hue(str) { var h = 0; for (var i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360; return h; }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  // ----- gallery -----
  function load(q) {
    return fetch('/api/tracks' + (q ? '?q=' + encodeURIComponent(q) : '')).then(function (r) { return r.json(); })
      .then(function (d) { tracks = d; cur = tracks.findIndex(function (t) { return t.id === curId; }); render(); })
      .catch(function () { toast('Could not load tracks'); });
  }
  function render() {
    grid.textContent = '';
    $('#empty').hidden = tracks.length > 0;
    $('#count').textContent = 'Gallery · ' + tracks.length + ' track' + (tracks.length === 1 ? '' : 's');
    tracks.forEach(function (t, i) {
      var card = el('article', 'card' + (t.id === curId ? ' playing' : ''));
      var h = hue(t.id);
      var cover = el('div', 'cover'); cover.style.background = '';
      cover.appendChild(el('span', '', t.media_type === 'video' ? '▶' : '♪'));
      var ov = el('div', 'ov', t.id === curId && !audio.paused ? '⏸' : '▶'); cover.appendChild(ov);
      cover.onclick = function () { play(i); };
      card.appendChild(cover);
      card.appendChild(el('div', 'title', t.title));
      card.appendChild(el('div', 'muted', (t.artist || 'Unknown artist') + ' · ' + t.ext.toUpperCase() + ' · ' + fmtSize(t.size)));
      card.appendChild(el('div', 'muted', '▶ ' + t.plays + ' plays · ' + t.created_at));
      var acts = el('div', 'acts');
      var dl = el('a', '', '⬇ Download'); dl.href = '/api/tracks/' + t.id + '/download'; acts.appendChild(dl);
      var sh = el('button', '', '🔗 Share'); sh.onclick = function () { share(t); }; acts.appendChild(sh);
      if (tokens[t.id]) { var del = el('button', 'del', '🗑 Delete'); del.onclick = function () { remove(t); }; acts.appendChild(del); }
      card.appendChild(acts); grid.appendChild(card);
    });
  }

  // ----- player -----
  function play(i) {
    if (i < 0 || i >= tracks.length) return;
    var t = tracks[i];
    var isVideo = t.media_type === 'video';

    if (t.id === curId) {
      if (isVideo) {
        video.paused ? video.play().catch(function () { toast('Could not play this video'); }) : video.pause();
      } else {
        audio.paused ? audio.play().catch(function () { toast('Could not play this audio'); }) : audio.pause();
      }
      return;
    }

    cur = i;
    curId = t.id;

    if (isVideo) {
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
      $('#player').hidden = true;
      video.hidden = false;
      video.src = '/api/tracks/' + t.id + '/stream';
      video.play().catch(function () { toast('Press play to start this video'); });
    } else {
      video.pause();
      video.removeAttribute('src');
      video.load();
      video.hidden = true;
      audio.src = '/api/tracks/' + t.id + '/stream';
      $('#player').hidden = false;
      audio.play().catch(function () { toast('Tap play to start'); });
    }

    $('#npTitle').textContent = t.title;
    $('#npArtist').textContent = t.artist || 'Unknown artist';
    document.title = '▶ ' + t.title;

    fetch('/api/tracks/' + t.id + '/play', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) { t.plays = d.plays; render(); })
      .catch(function () {});

    if ('mediaSession' in navigator && !isVideo) {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: t.title,
        artist: t.artist || 'Cloud Music'
      });
      navigator.mediaSession.setActionHandler('previoustrack', function () { play(cur - 1); });
      navigator.mediaSession.setActionHandler('nexttrack', function () { play(cur + 1); });
    }

    render();
  }
  function sync() { $('#pp').textContent = audio.paused ? '▶' : '⏸'; $('#eq').classList.toggle('on', !audio.paused); render(); }
  audio.addEventListener('play', sync); audio.addEventListener('pause', sync);
  audio.addEventListener('ended', function () { cur + 1 < tracks.length ? play(cur + 1) : sync(); });
  audio.addEventListener('timeupdate', function () {
    if (!audio.duration) return;
    $('#bar').value = audio.currentTime / audio.duration * 1000; $('#cur').textContent = fmtTime(audio.currentTime);
  });
  audio.addEventListener('loadedmetadata', function () { $('#dur').textContent = fmtTime(audio.duration); });
  audio.addEventListener('error', function () { if (audio.src) toast('Could not play this track'); });
  $('#bar').oninput = function () { if (audio.duration) audio.currentTime = this.value / 1000 * audio.duration; };
  $('#vol').oninput = function () { audio.volume = this.value / 100; }; audio.volume = 0.8;
  $('#pp').onclick = function () { audio.paused ? audio.play() : audio.pause(); };
  $('#prev').onclick = function () { play(cur - 1); }; $('#next').onclick = function () { play(cur + 1); };
  document.addEventListener('keydown', function (e) {
    if (e.target.tagName === 'INPUT' || !curId) return;
    if (e.code === 'Space') { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
  });

  // ----- share / delete -----
  function share(t) {
    var url = location.origin + '/s/' + t.id;
    if (navigator.share) { navigator.share({ title: t.title, text: t.artist || 'Listen on Cloud Music', url: url }).catch(function () {}); return; }
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(url).then(function () { toast('Share link copied!'); });
    else window.prompt('Copy this share link:', url);
  }
  function remove(t) {
    if (!confirm('Delete "' + t.title + '" from the cloud?')) return;
    fetch('/api/tracks/' + t.id, { method: 'DELETE', headers: { 'X-Delete-Token': tokens[t.id] || '' } }).then(function (r) {
      if (r.status === 204) {
        delete tokens[t.id]; saveTokens();
        if (curId === t.id) {
          audio.pause();
          audio.removeAttribute('src');
          video.pause();
          video.removeAttribute('src');
          video.hidden = true;
          $('#player').hidden = true;
          curId = null;
          document.title = 'Cloud Music Gallery';
        }
        toast('Deleted'); load($('#search').value.trim());
      } else toast('Could not delete');
    });
  }

  // ----- upload -----
  var drop = $('#drop'), file = $('#file'), busy = false, pending = [];
  ['dragenter', 'dragover'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
  drop.addEventListener('drop', function (e) { enqueue(e.dataTransfer.files); });
  file.onchange = function () { enqueue(file.files); file.value = ''; };
  function enqueue(list) { for (var i = 0; i < list.length; i++) pending.push(list[i]); next(); }
  function next() {
    if (busy || !pending.length) return;
    busy = true; var f = pending.shift();
    var row = el('div', 'q'); row.appendChild(el('div', '', f.name));
    var bar = el('div', 'bar'), fill = el('i'); bar.appendChild(fill); row.appendChild(bar); $('#queue').appendChild(row);
    var fd = new FormData(); fd.append('file', f);
    var x = new XMLHttpRequest(); x.open('POST', '/api/upload');
    x.upload.onprogress = function (e) { if (e.lengthComputable) fill.style.width = (e.loaded / e.total * 100) + '%'; };
    x.onload = function () {
      var d = {}; try { d = JSON.parse(x.responseText); } catch (e) {}
      if (x.status === 201) {
        tokens[d.track.id] = d.delete_token; saveTokens(); fill.style.width = '100%'; toast('Uploaded ' + d.track.title);
        setTimeout(function () { row.remove(); }, 1200); load($('#search').value.trim());
      } else { row.classList.add('err'); row.appendChild(el('div', '', d.error || 'Upload failed')); setTimeout(function () { row.remove(); }, 6000); }
      busy = false; next();
    };
    x.onerror = function () { row.classList.add('err'); row.appendChild(el('div', '', 'Network error')); busy = false; next(); };
    x.send(fd);
  }

  var timer; $('#search').oninput = function () { var v = this.value.trim(); clearTimeout(timer); timer = setTimeout(function () { load(v); }, 250); };
  load();
})();
