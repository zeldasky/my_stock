#!/usr/bin/env python
"""기존 진입점 유지용 래퍼.

계산 로직은 app/core 로 옮겼고, 웹 API 와 완전히 같은 경로를 쓴다.
종목·수량·매수가는 더 이상 이 파일에 하드코딩되지 않고 DB 의 거래 원장에서 나온다.

    python myStock.py                 # 기존과 동일하게 현황 출력
    python myStock.py history         # 일별 자산추이
    python -m app.cli --help          # 전체 명령
"""

import sys

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or None))
