import json
import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import db


APP_DB_PATH = ROOT_DIR / "app" / "app.sqlite3"
KOREA_REGIONS = {
    "전체": ["전체"],
    "서울특별시": ["전체", "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구", "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구", "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구"],
    "부산광역시": ["전체", "강서구", "금정구", "기장군", "남구", "동구", "동래구", "부산진구", "북구", "사상구", "사하구", "서구", "수영구", "연제구", "영도구", "중구", "해운대구"],
    "대구광역시": ["전체", "군위군", "남구", "달서구", "달성군", "동구", "북구", "서구", "수성구", "중구"],
    "인천광역시": ["전체", "강화군", "계양구", "남동구", "동구", "미추홀구", "부평구", "서구", "연수구", "옹진군", "중구"],
    "광주광역시": ["전체", "광산구", "남구", "동구", "북구", "서구"],
    "대전광역시": ["전체", "대덕구", "동구", "서구", "유성구", "중구"],
    "울산광역시": ["전체", "남구", "동구", "북구", "울주군", "중구"],
    "세종특별자치시": ["전체", "세종시"],
    "경기도": ["전체", "수원시", "성남시", "용인시", "고양시", "화성시", "부천시", "안산시", "남양주시", "안양시", "평택시", "시흥시", "파주시", "의정부시", "김포시", "광주시", "광명시", "군포시", "하남시", "오산시", "이천시", "안성시", "의왕시", "양주시", "포천시", "구리시", "여주시", "동두천시", "과천시", "가평군", "양평군", "연천군"],
    "강원특별자치도": ["전체", "춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시", "삼척시", "홍천군", "횡성군", "영월군", "평창군", "정선군", "철원군", "화천군", "양구군", "인제군", "고성군", "양양군"],
    "충청북도": ["전체", "청주시", "충주시", "제천시", "보은군", "옥천군", "영동군", "증평군", "진천군", "괴산군", "음성군", "단양군"],
    "충청남도": ["전체", "천안시", "공주시", "보령시", "아산시", "서산시", "논산시", "계룡시", "당진시", "금산군", "부여군", "서천군", "청양군", "홍성군", "예산군", "태안군"],
    "전북특별자치도": ["전체", "전주시", "군산시", "익산시", "정읍시", "남원시", "김제시", "완주군", "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군"],
    "전라남도": ["전체", "목포시", "여수시", "순천시", "나주시", "광양시", "담양군", "곡성군", "구례군", "고흥군", "보성군", "화순군", "장흥군", "강진군", "해남군", "영암군", "무안군", "함평군", "영광군", "장성군", "완도군", "진도군", "신안군"],
    "경상북도": ["전체", "포항시", "경주시", "김천시", "안동시", "구미시", "영주시", "영천시", "상주시", "문경시", "경산시", "의성군", "청송군", "영양군", "영덕군", "청도군", "고령군", "성주군", "칠곡군", "예천군", "봉화군", "울진군", "울릉군"],
    "경상남도": ["전체", "창원시", "진주시", "통영시", "사천시", "김해시", "밀양시", "거제시", "양산시", "의령군", "함안군", "창녕군", "고성군", "남해군", "하동군", "산청군", "함양군", "거창군", "합천군"],
    "제주특별자치도": ["전체", "제주시", "서귀포시"],
}


@st.cache_resource
def init_conn():
    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = db.get_conn(APP_DB_PATH)
    db.init_db(conn)
    return conn


def _render_submit_form(conn):
    st.subheader("새 마케팅 검증 작업")
    title = st.text_input("작업명", value="신규 카피 검증", help="작업 큐와 보고서에서 구분할 작업 이름입니다.")
    col1, col2 = st.columns(2)
    with col1:
        copy_a = st.text_area("카피 A", height=120, help="A안 광고 문구를 입력하세요.")
    with col2:
        copy_b = st.text_area("카피 B", height=120, help="B안 광고 문구를 입력하세요.")

    st.markdown("#### 캠페인 설명")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        product = st.text_input("제품", value="이너뷰티 젤리", help="검증 대상 제품/서비스명입니다.")
    with c2:
        category = st.text_input("카테고리", value="건강기능식품", help="제품이 속한 산업/상품군입니다.")
    with c3:
        tone = st.text_input("톤", value="밝고 자신감 있는 톤", help="카피의 말투/브랜드 톤앤매너입니다.")
    with c4:
        goal = st.text_input("목표", value="신규 고객 유입", help="캠페인의 1차 목적(예: 유입, 전환, 재구매)입니다.")
    description = st.text_area("추가 설명", value="", help="타겟 맥락, 제한 조건, 강조 포인트 등 추가 배경을 적습니다.")

    st.markdown("#### 페르소나 필터")
    f1, f2, f3, f4, f5 = st.columns(5)
    with f1:
        sex = st.selectbox("성별", options=["all", "남자", "여자"], index=0, help="페르소나 성별 필터입니다. all 선택 시 전체 성별 대상.")
    with f2:
        age_min = st.number_input("최소 나이", min_value=10, max_value=49, value=20, help="페르소나 최소 나이입니다.")
    with f3:
        age_max = st.number_input("최대 나이", min_value=10, max_value=49, value=39, help="페르소나 최대 나이입니다.")
    with f4:
        province = st.selectbox("지역(시/도)", options=list(KOREA_REGIONS.keys()), index=0, help="대한민국 시/도 기준 페르소나 지역 필터입니다.")
    with f5:
        district_options = KOREA_REGIONS.get(province, ["전체"])
        district = st.selectbox("세부지역(시군구)", options=district_options, index=0, help="선택한 시/도의 하위 시군구 필터입니다.")

    st.markdown("#### 실행 옵션")
    o1, o2, o3, o4, o5 = st.columns(5)
    with o1:
        profile = st.selectbox("프로파일", ["small", "standard"], index=0, help="small은 빠른 실행, standard는 더 많은 페르소나로 평가합니다.")
    with o2:
        evaluator = st.selectbox("평가기", ["ollama", "mock"], index=0, help="ollama는 실제 LLM 평가, mock은 빠른 테스트용 점수 생성입니다.")
    with o3:
        ollama_model = st.text_input("Ollama 모델", value="gemma4:e4b-it-q4_K_M", help="Ollama에 내려받은 모델 태그를 입력하세요.")
    with o4:
        max_personas = st.number_input(
            "최대 페르소나",
            min_value=8,
            max_value=200,
            value=24,
            help="평가에 사용할 페르소나 수 상한입니다. 최소 8, 최대 200, 권장 12~24(빠른 실험) / 40~80(품질 우선).",
        )
    with o5:
        eval_concurrency = st.number_input(
            "평가 동시성",
            min_value=1,
            max_value=8,
            value=2,
            help="동시 LLM 호출 수입니다. 최소 1, 최대 8, 권장 2~4.",
        )
    retrieval_k_per_bucket = st.number_input(
        "버킷당 검색 수",
        min_value=20,
        max_value=500,
        value=80,
        help="연령 버킷별 벡터 검색 후보 수입니다. 최소 20, 최대 500, 권장 60~120.",
    )

    submitted = st.button("작업 큐에 넣기", type="primary")
    if submitted:
        if not copy_a.strip() or not copy_b.strip():
            st.error("카피 A/B는 필수입니다.")
            return
        if age_min > age_max:
            st.error("나이 범위가 올바르지 않습니다.")
            return

        payload = {
            "title": title,
            "copy_a": copy_a.strip(),
            "copy_b": copy_b.strip(),
            "product": product.strip(),
            "category": category.strip(),
            "tone": tone.strip(),
            "goal": goal.strip(),
            "description": description.strip(),
            "profile": profile,
            "evaluator": evaluator,
            "ollama_model": ollama_model.strip(),
            "max_personas": int(max_personas),
            "retrieval_k_per_bucket": int(retrieval_k_per_bucket),
            "eval_concurrency": int(eval_concurrency),
            "persona_filter": {
                "sex": sex,
                "age_min": int(age_min),
                "age_max": int(age_max),
                "province": "" if province == "전체" else province.strip(),
                "district": "" if district == "전체" else district.strip(),
            },
        }
        job_id = db.enqueue_job(conn=conn, title=title, payload=payload)
        db.add_notification(
            conn=conn,
            job_id=job_id,
            n_type="info",
            title=f"작업 #{job_id} 등록",
            message="작업 큐에 추가되었습니다.",
        )
        st.success(f"작업 #{job_id} 등록 완료")


def _render_queue(conn):
    st.subheader("작업 큐")
    st.info(
        "백그라운드 워커를 별도 프로세스로 실행하세요: "
        "`./venv/bin/python -m app.worker_main --poll-interval-sec 2`"
    )
    if st.button("새로고침"):
        st.rerun()

    rows = db.fetch_jobs(conn, limit=200)
    table = []
    for r in rows:
        table.append(
            {
                "id": int(r["id"]),
                "status": r["status"],
                "title": r["title"],
                "created_at": r["created_at"],
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
                "error_message": r["error_message"],
            }
        )
    st.dataframe(table, use_container_width=True)


def _render_notifications(conn):
    st.subheader("알림")
    unread = db.unread_notification_count(conn)
    st.caption(f"읽지 않음: {unread}건")
    rows = db.fetch_notifications(conn, limit=100)
    for r in rows:
        n_id = int(r["id"])
        title = r["title"]
        message = r["message"]
        n_type = r["type"]
        is_read = bool(r["is_read"])
        badge = "읽음" if is_read else "새 알림"
        with st.expander(f"[{badge}] ({n_type}) {title}"):
            st.write(message)
            st.caption(f"생성 시각: {r['created_at']}")
            if not is_read and st.button("읽음 처리", key=f"read_{n_id}"):
                db.mark_notification_read(conn, n_id)
                st.rerun()


def _render_reports(conn):
    st.subheader("보고서 조회")
    rows = db.fetch_jobs(conn, limit=200)
    completed_ids = [int(r["id"]) for r in rows if r["status"] == "completed"]
    if not completed_ids:
        st.info("완료된 작업이 없습니다.")
        return
    selected = st.selectbox("작업 선택", options=completed_ids)
    selected_job = None
    for r in rows:
        if int(r["id"]) == int(selected):
            selected_job = r
            break
    payload = {}
    if selected_job is not None:
        try:
            payload = json.loads(selected_job["payload_json"])
        except Exception:  # noqa: BLE001
            payload = {}

    result_row = db.fetch_job_result(conn, selected)
    if result_row is None:
        st.warning("결과 레코드를 찾지 못했습니다.")
        return
    report_json_path = Path(result_row["report_json_path"])
    if not report_json_path.exists():
        st.error(f"리포트 파일이 없습니다: {report_json_path}")
        return
    report_obj = json.loads(report_json_path.read_text(encoding="utf-8"))
    st.markdown(f"### 작업 #{selected} 결과")
    if payload:
        st.write("#### 작업 설정값")
        st.json(
            {
                "title": payload.get("title", ""),
                "profile": payload.get("profile", ""),
                "evaluator": payload.get("evaluator", ""),
                "ollama_model": payload.get("ollama_model", ""),
                "max_personas": payload.get("max_personas", ""),
                "retrieval_k_per_bucket": payload.get("retrieval_k_per_bucket", ""),
                "eval_concurrency": payload.get("eval_concurrency", ""),
                "persona_filter": payload.get("persona_filter", {}),
            },
            expanded=False,
        )
        st.write("#### 입력 카피")
        st.write(f"- 카피 A: {payload.get('copy_a', '')}")
        st.write(f"- 카피 B: {payload.get('copy_b', '')}")

    st.write(f"- 최종 추천: **{report_obj['report']['final_winner']}**")
    st.write(f"- 실행 시간(초): {report_obj.get('runtime', {}).get('elapsed_sec', 0):.2f}")
    st.write("#### 연령대 요약")
    st.json(report_obj["report"]["summary_by_bucket"], expanded=False)
    st.write("#### 핵심 근거")
    for reason in report_obj["report"]["key_reasons"]:
        st.write(f"- {reason}")
    st.write("#### 원본 파일")
    st.code(str(report_json_path))


def main():
    st.set_page_config(page_title="마케팅 검증 앱", layout="wide")
    st.title("Nemotron 마케팅 검증 대시보드")
    conn = init_conn()
    unread = db.unread_notification_count(conn)
    st.caption(f"읽지 않은 알림: {unread}건")

    tabs = st.tabs(["작업 등록", "큐", "알림", "보고서"])
    with tabs[0]:
        _render_submit_form(conn)
    with tabs[1]:
        _render_queue(conn)
    with tabs[2]:
        _render_notifications(conn)
    with tabs[3]:
        _render_reports(conn)


if __name__ == "__main__":
    main()
