# src/pages/search_filter_page.py
"""맛집 검색 필터 페이지 (목록 표시)"""

import pandas as pd
import streamlit as st

from pages import search_map_page
from config.constants import LARGE_CATEGORIES, LARGE_CATEGORIES_NOT_USED
from utils.app import What2EatApp
from utils.auth import get_current_user
from utils.dialogs import change_location
from utils.firebase_logger import get_firebase_logger
from utils.search_filter import SearchFilter
from utils.api import APIRequester


def _log_user_activity(activity_type: str, detail: dict) -> bool:
    """사용자 활동 로깅 헬퍼 메서드"""
    logger = get_firebase_logger()
    if "user_info" not in st.session_state or not st.session_state.user_info:
        return False

    uid = st.session_state.user_info.get("localId")
    if not uid:
        return False

    return logger.log_user_activity(uid, activity_type, detail)


def initialize_session_state():
    """세션 상태 초기화"""
    if "search_results" not in st.session_state:
        st.session_state.search_results = None
    if "search_display_count" not in st.session_state:
        st.session_state.search_display_count = 15
    if "search_filters" not in st.session_state:
        st.session_state.search_filters = {
            "radius_km": 5.0,
            "large_categories": [],
            "middle_categories": [],
            "sort_by": "개인화",
            "period": "전체",
        }


def render_filter_ui(app: What2EatApp, search_filter: SearchFilter):
    """필터 UI 렌더링 (폼 기반)"""
    st.subheader("🔍 검색 필터")

    # 위치 설정 (폼 외부)
    col1, col2 = st.columns([3, 1])
    with col1:
        if "address" in st.session_state:
            st.info(f"📍 현재 위치: {st.session_state.address}")
        else:
            st.warning("⚠️ 위치를 설정해주세요")
    with col2:
        if st.button("위치 변경", use_container_width=True):
            change_location()
            _log_user_activity("location_change", {"from_page": "search_filter"})

    st.markdown("---")

    # 카테고리 선택 (폼 외부 - 동적 업데이트를 위해)
    st.markdown("### 🍽️ 카테고리")

    # 대분류 카테고리
    large_categories = [cat for cat in LARGE_CATEGORIES if cat not in LARGE_CATEGORIES_NOT_USED]
    selected_large = st.multiselect(
        "대분류 카테고리",
        options=large_categories,
        default=st.session_state.search_filters["large_categories"],
        help="대분류를 선택하면 해당하는 중분류만 표시됩니다",
        key="large_category_filter"
    )

    # 중분류 카테고리 (대분류 선택에 따라 동적으로 필터링)
    if selected_large:
        df_filtered_by_large = app.df_diner[
            app.df_diner["diner_category_large"].isin(selected_large)
        ]
        middle_categories = sorted(
            df_filtered_by_large["diner_category_middle"].dropna().unique()
        )
        
        # 이전에 선택된 중분류 중 현재 대분류에 해당하는 것만 유지
        valid_middle_defaults = [
            cat
            for cat in st.session_state.search_filters["middle_categories"]
            if cat in middle_categories
        ]
        
        selected_middle = st.multiselect(
            "중분류 카테고리",
            options=middle_categories,
            default=valid_middle_defaults,
            help=f"{len(middle_categories)}개의 중분류 카테고리 사용 가능",
            key="middle_category_filter"
        )
    else:
        # 대분류가 선택되지 않은 경우 빈 목록 표시
        selected_middle = st.multiselect(
            "중분류 카테고리",
            options=[],
            default=[],
            disabled=True,
            help="먼저 대분류 카테고리를 선택해주세요",
            key="middle_category_filter"
        )

    st.markdown("---")

    # 폼으로 나머지 필터 감싸기
    with st.form("search_filter_form", clear_on_submit=False):
        # 반경 설정
        radius_km = st.slider(
            "검색 반경 (km)",
            min_value=1.0,
            max_value=20.0,
            value=st.session_state.search_filters["radius_km"],
            step=0.5,
        )

        # 정렬 기준
        st.markdown("### 📊 정렬 기준")
        sort_by = st.radio(
            "정렬 방식",
            options=["개인화", "숨찐맛", "평점", "리뷰", "거리순"],
            index=["개인화", "숨찐맛", "평점", "리뷰", "거리순"].index(
                st.session_state.search_filters["sort_by"]
            ),
            horizontal=True,
        )

        # 기간 필터
        st.markdown("### 📅 기간")
        period = st.selectbox(
            "기간 선택",
            options=["전체", "1개월", "3개월"],
            index=["전체", "1개월", "3개월"].index(
                st.session_state.search_filters["period"]
            ),
        )

        # 검색 버튼
        st.markdown("---")
        submitted = st.form_submit_button("🔍 검색하기", type="primary", use_container_width=True)

        if submitted:
            # 폼 제출 시 세션 상태 업데이트 (카테고리는 폼 외부에서 이미 처리됨)
            st.session_state.search_filters["radius_km"] = radius_km
            st.session_state.search_filters["large_categories"] = selected_large
            st.session_state.search_filters["middle_categories"] = selected_middle
            st.session_state.search_filters["sort_by"] = sort_by
            st.session_state.search_filters["period"] = period
            return True

    return False


def render_restaurant_dataframe(df_results):
    """음식점 목록을 DataFrame으로 렌더링"""
    st.subheader(f"📋 검색 결과 ({len(df_results)}개)")

    if len(df_results) == 0:
        st.info("검색 결과가 없습니다. 필터 조건을 변경해보세요.")
        return

    # 표시할 개수
    display_count = st.session_state.search_display_count
    df_display = df_results.head(display_count).copy()
    df_display["카테고리"] = df_display["diner_category_middle"].fillna(df_display["diner_category_large"])
    # DataFrame 표시용 데이터 준비
    # 음식점명을 마크다운 링크 형식으로 변환
    display_data = {
        "링크": [f"https://place.map.kakao.com/{x}" for x in df_display["diner_idx"].tolist()],
        "음식점명": df_display["diner_name"].tolist(),
        "카테고리": df_display["카테고리"].tolist(),
        "등급": df_display["diner_grade"].apply(lambda x: "⭐" * int(x) if x else "").tolist(),
        "리뷰수": df_display["diner_review_cnt"].fillna(0).astype(int).tolist(),
        "거리(km)": df_display["distance"].round(1).tolist() if "distance" in df_display.columns else [0] * len(df_display),
    }

    if "personalized_score" in df_display.columns:
        display_data["개인화 점수"] = df_display["personalized_score"].tolist()

    df_to_display = pd.DataFrame(display_data)

    # DataFrame 표시 with column configuration
    st.dataframe(
        df_to_display,
        column_config={
            "음식점명": st.column_config.TextColumn("음식점명", width="medium"),
            "링크": st.column_config.LinkColumn("링크", width="small", display_text="🔗"),
            "카테고리": st.column_config.TextColumn("카테고리", width="small"),
            "등급": st.column_config.TextColumn("등급", width="small"),
            "리뷰수": st.column_config.NumberColumn("리뷰수", width="small"),
            "거리(km)": st.column_config.NumberColumn("거리(km)", width="small", format="%.1f"),
        },
        hide_index=True,
        use_container_width=True,
        height=600,
    )

    # 더보기 버튼
    if len(df_results) > display_count:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button(
                f"더보기 ({display_count}/{len(df_results)}개 표시 중)",
                use_container_width=True,
                type="secondary",
            ):
                st.session_state.search_display_count += 15
                st.rerun()
    else:
        st.success(f"✅ 모든 {len(df_results)}개 음식점을 표시했습니다.")


def render():
    """검색 필터 페이지 렌더링"""
    # 페이지 방문 로그
    _log_user_activity("page_visit", {"page_name": "search_filter"})

    # 앱 인스턴스 가져오기
    if "app" not in st.session_state:
        st.session_state.app = What2EatApp()
    app = st.session_state.app

    # 세션 상태 초기화
    initialize_session_state()

    # 검색 필터 인스턴스
    search_filter = SearchFilter(app.df_diner)

    st.title("🔍 맛집 검색")

    # 위치 확인
    if "address" not in st.session_state or "user_lat" not in st.session_state:
        st.warning("⚠️ 위치를 먼저 설정해주세요.")
        if st.button("위치 설정하기"):
            change_location()
        return

    # 필터 UI (폼 기반, 단일 레이아웃)
    with st.expander("🔍 검색 필터 설정", expanded=True):
        search_clicked = render_filter_ui(app, search_filter)

    # 검색 실행
    if search_clicked or st.session_state.search_results is not None:
        if search_clicked:
            # 필터 적용
            filters = st.session_state.search_filters
            df_results = search_filter.apply_filters(
                user_lat=st.session_state.user_lat,
                user_lon=st.session_state.user_lon,
                radius_km=filters["radius_km"],
                large_categories=filters["large_categories"]
                if filters["large_categories"]
                else None,
                middle_categories=filters["middle_categories"]
                if filters["middle_categories"]
                else None,
                sort_by=filters["sort_by"],
                period=filters["period"],
            )

            if filters["sort_by"] == "개인화":
                diner_ids = df_results["diner_idx"].tolist()
                firebase_uid = get_current_user()["localId"]
                
                try:
                    # Call personal recommendation API
                    api = APIRequester(endpoint=st.secrets["API_URL"])
                    response = api.post("/rec/personal", data={
                        "diner_ids": diner_ids,
                        "firebase_uid": firebase_uid
                    }).json()
                    
                    personalized_diner_ids = response["diner_ids"]
                    personalized_scores = response["scores"]
                    
                    # Handle case where response has fewer items than original
                    if len(personalized_diner_ids) < len(diner_ids):
                        # Get remaining diner_ids not in personalized response
                        # These diners are **cold-start** diners, not in train data
                        remaining_ids = [id for id in diner_ids if id not in personalized_diner_ids]
                        # Combine personalized + remaining in original order
                        final_diner_ids = personalized_diner_ids + remaining_ids
                        scores = personalized_scores + ["NA"]*len(remaining_ids)
                    else:
                        final_diner_ids = personalized_diner_ids.copy()
                        scores = personalized_scores.copy()
                    
                    # Reorder df_results based on personalized order
                    df_results = df_results.set_index("diner_idx").reindex(final_diner_ids).reset_index()
                    df_results["personalized_score"] = scores
                    
                except Exception as e:
                    st.warning(f"개인화 추천을 불러오는데 실패했습니다. 기본 정렬을 사용합니다: {e}")
                    # Keep original df_results ordering as fallback
            else:
                # todo: 윤선님, 성록님 개발 내용
                pass

            # 결과 저장
            st.session_state.search_results = df_results
            # 표시 개수 초기화
            st.session_state.search_display_count = 15

            # 로깅
            _log_user_activity(
                "search_executed",
                {
                    "filters": filters,
                    "results_count": len(df_results),
                },
            )

        # 결과 표시
        df_results = st.session_state.search_results

        # 지도 보기 버튼
        if len(df_results) > 0:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                if st.button("🗺️ 지도에서 보기", use_container_width=True, type="primary"):
                    search_map_page.render_dialog()
                    # CHECKLIST: 지도 페이지 렌더링 버전 말고  지도 페이지로 이동시 
                    # st.switch_page(st.Page(search_map_page.render, url_path="map", title="지도 보기", icon="🗺️"))

        st.markdown("---")

        # 목록 표시 (DataFrame)
        render_restaurant_dataframe(df_results)
    else:
        st.info("👆 위에서 필터를 설정하고 검색해보세요!")

