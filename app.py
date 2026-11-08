"""WoW Forever: ежедневный поиск выгодных товаров.

  python app.py              окно приложения
  python app.py --run-once   один прогон без окна (для планировщика), отчёт в папке данных
  python app.py --demo       окно в демо-режиме
"""
import argparse
import sys

from forever_deals import appdata, runner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-once", action="store_true")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    h = appdata.home()
    cfg = appdata.load_cfg(h)
    if a.demo:
        cfg["demo"] = True
    if a.run_once:
        try:
            res, md, path, _ = runner.run_search(h, cfg, print)
        except Exception as exc:
            print("Ошибка:", exc, file=sys.stderr)
            return 1
        print("Отчёт:", path)
        return 0
    from forever_deals.gui import App
    App(h, cfg).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
