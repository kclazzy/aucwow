// Чистая логика страницы для телефона (без DOM): разбор значений таблицы, сортировка, поиск, категории.
(function (root) {
  "use strict";

  // Значение ячейки -> число (для сортировки) или строка. "н/д" и "—" всегда считаются самыми маленькими.
  function sortKey(text) {
    var t = String(text == null ? "" : text).trim();
    if (t === "" || t === "—" || t === "н/д") return -Infinity;
    var money = t.match(/^(?:(\d+)\s*з)?\s*(?:(\d+)\s*с)?\s*(?:(\d+)\s*м)?$/);
    if (money && (money[1] || money[2] || money[3])) {
      return (+money[1] || 0) * 10000 + (+money[2] || 0) * 100 + (+money[3] || 0);
    }
    var num = t.replace(/^×/, "").replace(/,/g, "").replace(/%$/, "");
    if (/^-?\d+(\.\d+)?$/.test(num)) return parseFloat(num);
    return t.toLowerCase();
  }

  function compare(a, b) {
    var ta = typeof a, tb = typeof b;
    if (ta === tb) return a < b ? -1 : a > b ? 1 : 0;
    return ta === "number" ? -1 : 1;           // числа раньше текста
  }

  function sortRows(rows, col, desc) {
    var out = rows.slice();
    out.sort(function (x, y) {
      var c = compare(sortKey(x.v[col]), sortKey(y.v[col]));
      return desc ? -c : c;
    });
    return out;
  }

  function filterRows(rows, query) {
    var q = String(query || "").trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(function (r) {
      return r.v.some(function (cell) { return String(cell).toLowerCase().indexOf(q) !== -1; });
    });
  }

  function categoriesOf(rows, col) {
    var n = {};
    rows.forEach(function (r) { n[r.v[col]] = (n[r.v[col]] || 0) + 1; });
    return Object.keys(n).map(function (k) { return [k, n[k]]; })
      .sort(function (a, b) { return b[1] - a[1] || (a[0] < b[0] ? -1 : 1); });
  }

  var api = { sortKey: sortKey, sortRows: sortRows, filterRows: filterRows, categoriesOf: categoriesOf };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.FD = api;
})(typeof window !== "undefined" ? window : globalThis);
