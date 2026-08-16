/* 차트 호버 툴팁 + 종목 검색 자동완성. 없어도 페이지는 정상 동작한다. */

(function () {
  "use strict";

  /* ---------------- 차트 툴팁 ---------------- */

  document.querySelectorAll("[data-chart]").forEach(function (wrap) {
    var points = JSON.parse(wrap.dataset.points || "[]");
    if (!points.length) return;

    var labels = JSON.parse(wrap.dataset.labels || "{}");
    var viewWidth = parseFloat(wrap.dataset.width) || 1000;
    var svg = wrap.querySelector("svg");
    var dot = wrap.querySelector(".hit-dot");
    var tip = wrap.querySelector(".tooltip");

    function nearest(viewX) {
      var best = points[0];
      var bestGap = Math.abs(points[0].x - viewX);
      for (var i = 1; i < points.length; i++) {
        var gap = Math.abs(points[i].x - viewX);
        if (gap < bestGap) { bestGap = gap; best = points[i]; }
      }
      return best;
    }

    function move(clientX) {
      var box = svg.getBoundingClientRect();
      var scale = viewWidth / box.width;              // 뷰박스 좌표로 환산
      var point = nearest((clientX - box.left) * scale);

      dot.setAttribute("cx", point.x);
      dot.setAttribute("cy", point.y);
      dot.style.opacity = "1";

      tip.innerHTML =
        "<b>" + point.d + "</b><br>" +
        labels.v + " " + point.v +
        (point.c ? "<br>" + labels.c + " " + point.c : "") +
        (point.r ? "<br>" + labels.r + " " + point.r : "");
      tip.style.left = (point.x / scale) + "px";
      tip.style.top = (point.y * (box.height / (svg.viewBox.baseVal.height || 300))) + "px";
      tip.style.opacity = "1";
    }

    function hide() {
      dot.style.opacity = "0";
      tip.style.opacity = "0";
    }

    svg.addEventListener("mousemove", function (e) { move(e.clientX); });
    svg.addEventListener("mouseleave", hide);
    svg.addEventListener("touchmove", function (e) {
      if (e.touches.length) move(e.touches[0].clientX);
    }, { passive: true });
    svg.addEventListener("touchend", hide);
  });

  /* ---------------- 종목 검색 자동완성 ---------------- */

  var search = document.querySelector("[data-instrument-search]");
  if (!search) return;

  var list = document.getElementById("instrument-options");
  var symbolField = document.querySelector("[name=new_symbol]");
  var marketField = document.querySelector("[name=new_market]");
  var nameField = document.querySelector("[name=new_name]");
  var selectField = document.querySelector("[name=instrument_id]");
  var timer = null;
  var found = [];

  search.addEventListener("input", function () {
    var query = search.value.trim();
    clearTimeout(timer);
    if (query.length < 1) return;

    timer = setTimeout(function () {
      fetch("/api/v1/instruments/search?q=" + encodeURIComponent(query))
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) {
          found = rows;
          list.innerHTML = "";
          rows.forEach(function (row) {
            var option = document.createElement("option");
            option.value = row.name_ko + " (" + row.symbol + ")";
            list.appendChild(option);
          });
        })
        .catch(function () { /* 검색 실패해도 수동 입력은 가능하다 */ });
    }, 220);
  });

  search.addEventListener("change", function () {
    var picked = found.find(function (row) {
      return search.value === row.name_ko + " (" + row.symbol + ")";
    });
    if (!picked) return;

    if (picked.instrument_id && selectField) {
      selectField.value = picked.instrument_id;   // 이미 등록된 종목
      if (symbolField) symbolField.value = "";
    } else {
      if (selectField) selectField.value = "";
      if (symbolField) symbolField.value = picked.symbol;
      if (marketField) marketField.value = picked.market;
      if (nameField) nameField.value = picked.name_ko;
    }
  });
})();
