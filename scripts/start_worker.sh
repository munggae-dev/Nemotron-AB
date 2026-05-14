#!/bin/sh
# Nemotron-AB 워커 기동 헬퍼.
# 환경 변수 NEMOTRON_AB_PY 가 설정돼 있으면 그 경로로 실행, 아니면 현재 PATH의 python.

PY="${NEMOTRON_AB_PY:-python}"
exec "$PY" -m nemotron_ab.worker_main \
  --task-parallelism 4 \
  --poll-interval-sec 2 \
  --max-jobs-per-tick 50 \
  "$@"
