import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const L = createRequire(import.meta.url)("../forever_deals/mobile/logic.js");

test("sortKey понимает деньги, множители, числа и текст", () => {
  assert.equal(L.sortKey("1з 20с 5м"), 12005);
  assert.equal(L.sortKey("45м"), 45);
  assert.equal(L.sortKey("×3.5"), 3.5);
  assert.equal(L.sortKey("12.5"), 12.5);
  assert.equal(L.sortKey("н/д"), -Infinity);
  assert.equal(L.sortKey("—"), -Infinity);
  assert.equal(L.sortKey("Ткань"), "ткань");
});

test("sortRows сортирует по колонке в обе стороны и держит н/д внизу при убывании", () => {
  const rows = [{ v: ["a", "2з"] }, { v: ["b", "н/д"] }, { v: ["c", "10с"] }];
  assert.deepEqual(L.sortRows(rows, 1, true).map(r => r.v[0]), ["a", "c", "b"]);
  assert.deepEqual(L.sortRows(rows, 1, false).map(r => r.v[0]), ["b", "c", "a"]);
  assert.deepEqual(rows.map(r => r.v[0]), ["a", "b", "c"]);       // исходный массив не меняется
});

test("filterRows ищет по всем колонкам без учёта регистра", () => {
  const rows = [{ v: ["Льняная ткань", "Ткань"] }, { v: ["Руда", "Металл"] }];
  assert.equal(L.filterRows(rows, "ТКАНЬ").length, 1);
  assert.equal(L.filterRows(rows, "").length, 2);
  assert.equal(L.filterRows(rows, "  ").length, 2);
  assert.equal(L.filterRows(rows, "нет такого").length, 0);
});

test("categoriesOf считает категории по убыванию", () => {
  const rows = [{ v: ["x", "B"] }, { v: ["y", "A"] }, { v: ["z", "B"] }];
  assert.deepEqual(L.categoriesOf(rows, 1), [["B", 2], ["A", 1]]);
});
