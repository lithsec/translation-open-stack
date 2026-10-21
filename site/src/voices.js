// Haitian Creole voice lineup: pick a sentence, hear every voice read it.
// Blind mode shuffles the rows and hides names and scores.
(function () {
  var el = document.getElementById("voice-data");
  if (!el) return;
  var data = JSON.parse(el.textContent);
  var picker = document.getElementById("picker");
  var sentence = document.getElementById("sentence");
  var rows = document.getElementById("vrows");
  var blindBox = document.getElementById("blind");
  var cur = 0;
  var order = data.voices.map(function (_, i) { return i; });

  function shuffle(a) {
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  function render() {
    picker.querySelectorAll("button").forEach(function (b, i) {
      b.setAttribute("aria-pressed", i === cur ? "true" : "false");
    });
    sentence.innerHTML = "";
    var s = document.createElement("small");
    s.textContent = "Sentence " + (cur + 1) + " of " + data.sentences.length;
    sentence.appendChild(s);
    sentence.appendChild(document.createTextNode(data.sentences[cur]));
    rows.innerHTML = "";
    order.forEach(function (vi, pos) {
      var v = data.voices[vi];
      var row = document.createElement("div");
      row.className = "vrow";
      var left = document.createElement("div");
      var name = document.createElement("div");
      name.className = "name";
      var real = document.createElement("span");
      real.className = "real";
      real.textContent = v.name;
      var alias = document.createElement("span");
      alias.className = "alias";
      alias.textContent = "Voice " + (pos + 1);
      name.appendChild(real); name.appendChild(alias);
      var meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = v.meta;
      left.appendChild(name); left.appendChild(meta);
      var audio = document.createElement("audio");
      audio.controls = true;
      audio.preload = "none";
      audio.src = data.audioBase + v.file + "__" + cur + ".mp3";
      audio.setAttribute("aria-label", (document.body.classList.contains("blind") ? "Voice " + (pos + 1) : v.name) + ", sentence " + (cur + 1));
      audio.addEventListener("play", function () {
        rows.querySelectorAll("audio").forEach(function (a) { if (a !== audio) a.pause(); });
      });
      row.appendChild(left); row.appendChild(audio);
      rows.appendChild(row);
    });
  }

  data.sentences.forEach(function (_, i) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = String(i + 1);
    b.setAttribute("aria-label", "Sentence " + (i + 1));
    b.addEventListener("click", function () { cur = i; render(); });
    picker.appendChild(b);
  });
  blindBox.addEventListener("change", function () {
    document.body.classList.toggle("blind", blindBox.checked);
    order = blindBox.checked ? shuffle(order.slice()) : data.voices.map(function (_, i) { return i; });
    render();
  });
  render();
})();
