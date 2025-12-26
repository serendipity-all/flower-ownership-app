# -*- coding: utf-8 -*-
"""
Created on Fri Nov 28 11:32:03 2025

@author: delia_chang
"""
import re
import io
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt


# =========================================================
# ✅ 固定資料來源 + 固定欄位（朋友不用再填）
# =========================================================
FIXED_SHEET_URL = "https://docs.google.com/spreadsheets/d/1-_towzRVHsn7spZrKNdc00RGNG_3xq8_JQ75sPY9HbI/edit?gid=1203973994#gid=1203973994"

DESC_COLS = ["品", "花名", "獲得方式", "備註"]  # 描述欄（原 A~D）
OWNER_START_COL = "名字"                        # 擁有人欄第一欄
TYPE_COL = "花名"                               # 種類欄（預設用花名當種類）
# 若你要用「品」當種類，把上一行改成 TYPE_COL = "品"

# 64 格實際在畫面上的排列（None 代表 X / 無效格）
TASK_GRID_LAYOUT = [
    [28, 24, 20, None, 16, 12,  8, None,  4,  0],
    [29, 25, 21, None, 17, 13,  9, None,  5,  1],
    [30, 26, 22, None, 18, 14, 10, None,  6,  2],
    [31, 27, 23, None, 19, 15, 11, None,  7,  3],
    [None, None, None, None, None, None, None, None, None, None],
    [60, 56, 52, None, 48, 44, 40, None, 36, 32],
    [61, 57, 53, None, 49, 45, 41, None, 37, 33],
    [62, 58, 54, None, 50, 46, 42, None, 38, 34],
    [63, 59, 55, None, 51, 47, 43, None, 39, 35],
]

# =========================================================


# ---------- 工具函式 ----------
def google_sheet_to_csv_url(sheet_url: str, gid: str = None) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url)
    if not m:
        raise ValueError("URL 看起來不像 Google Sheets")
    sheet_id = m.group(1)

    if gid is None:
        m2 = re.search(r"gid=([0-9]+)", sheet_url)
        gid = m2.group(1) if m2 else "0"

    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


# @st.cache_data(show_spinner=False) 這行因為沒有設定時間，所以會造成無法取得最新資料
@st.cache_data(show_spinner=False, ttl=600)  # ttl 單位是秒，這樣是600秒自動更新一次，如果不希望一直更新，直接把這行block掉就好
def load_sheet(sheet_url: str):
    """
    讀取 Google Sheet，並回傳：
    - df: 資料表
    - loaded_at: 資料載入時間（Asia/Taipei）
    """
    csv_url = google_sheet_to_csv_url(sheet_url)
    df = pd.read_csv(csv_url)

    # 使用台北時區時間
    loaded_at = pd.Timestamp.now(tz="Asia/Taipei")
    return df, loaded_at

def normalize_name(x):
    """基本清理：去 NaN、怪空白、trim。**不做 s10. 格式處理**。"""
    if pd.isna(x):
        return ""
    s = str(x)

    # 清掉常見怪空白（含全形、NBSP、零寬）
    s = s.replace("\u3000", " ")
    s = s.replace("\xa0", " ")
    s = re.sub(r"[\u200b\u200c\u200d\uFEFF]", "", s)

    s = s.strip()
    return s


def split_names(cell: str):
    """
    把同一格可能塞的多個「名單字串」拆開：
    支援：、 , ; / 換行 以及多空白
    """
    if not cell:
        return []
    parts = re.split(r"[、,;/\n\r]+|\s{2,}", cell)
    parts = [p.strip() for p in parts if p.strip()]
    return parts


def canonicalize_name(name: str) -> str:
    """
    將名單整理成統一格式：
    1. s/S + 數字 + (可選 . 或全形．) + 名字
       → 統一為 s{no}.{name} 且 s 一律小寫
    2. 其他格式則只做 trim（不強制改型態）
    """
    s = normalize_name(name)
    if not s:
        return ""

    # 匹配 s10.花明月、S10花明月、10.花明月、s10．花明月 等等
    m = re.match(r"^[sS]?(\d+)[\.．]?(.*)$", s)
    if m:
        num, rest = m.groups()
        rest = rest.strip()
        if rest:
            return f"s{num}.{rest}"
        else:
            return f"s{num}"
    return s


def extract_unique_names_from_row(row) -> list:
    """
    從一整列（所有擁有人欄）中取出：
    - 拆開每格可能的多名單
    - normalize + canonicalize
    - 在「同一朵花（同一 row）」裡去掉重複（要求 2）
    回傳：該 row 內「唯一的名單清單」
    """
    seen = set()
    names = []
    for v in row:
        base = normalize_name(v)
        if not base:
            continue
        for token in split_names(base):
            token = canonicalize_name(token)
            if token and token not in seen:
                seen.add(token)
                names.append(token)
    return names


def df_with_flower_index(df: pd.DataFrame, name_col: str = "花名") -> pd.DataFrame:
    """
    顯示用的小工具：
    如果有「花名」這個欄位，就把它設成 index，
    這樣在 st.dataframe 水平捲動的時候，左邊花名會固定。
    """
    if name_col in df.columns:
        df = df.copy()
        df = df.set_index(name_col)
    return df


def make_unique_columns(columns):
    """避免欄名重複造成顯示/排序異常"""
    seen = {}
    new_cols = []
    for col in columns:
        if col not in seen:
            seen[col] = 0
            new_cols.append(col)
        else:
            seen[col] += 1
            new_cols.append(f"{col}_{seen[col]}")
    return new_cols


def compute_owner_counts(df, desc_cols, owner_start_col):
    """
    這裡會：
    - 用 extract_unique_names_from_row 做「每朵花唯一名單」
    - owner_count = 名單數量（已去重）
    - owners = 逗號串名單（已 canonical：s10.xxx）
    - item_desc = 合併描述欄
    """
    cols = list(df.columns)
    if owner_start_col not in cols:
        raise ValueError(f"找不到 OWNER_START_COL：{owner_start_col}")

    start_idx = cols.index(owner_start_col)
    owner_cols = cols[start_idx:]

    owner_df = df[owner_cols]

    unique_names_series = owner_df.apply(extract_unique_names_from_row, axis=1)

    owner_count = unique_names_series.apply(len)
    owners_str = unique_names_series.apply(lambda names: ", ".join(names))

    out = df.copy()
    out["owner_count"] = owner_count
    out["owners"] = owners_str
    out["item_desc"] = out[desc_cols].astype(str).agg(" | ".join, axis=1)

    # owners_norm 仍然保留原始清理版（給其他地方需要原格內容用）
    owners_norm = owner_df.map(normalize_name)

    return out, owner_cols, owners_norm


def person_stats(df, person_name, type_col, desc_cols, owner_start_col):
    """
    指定人員統計：
    - 用 extract_unique_names_from_row 判斷 row 是否包含該名單
    - 因為 get_all_names 用的也是 canonicalize_name，
      所以 person_name 已經是 s10.xxx 的統一格式
    """
    cols = list(df.columns)
    start_idx = cols.index(owner_start_col)
    owner_cols = cols[start_idx:]

    owner_df = df[owner_cols]

    # 每 row 名單（已去重 + canonical）
    unique_names_series = owner_df.apply(extract_unique_names_from_row, axis=1)

    has_person = unique_names_series.apply(lambda names: person_name in names)

    safe_cols = []
    for c in desc_cols + [type_col]:
        if c not in safe_cols:
            safe_cols.append(c)

    owned_df = df.loc[has_person, safe_cols].copy()
    owned_df["item_desc"] = owned_df[desc_cols].astype(str).agg(" | ".join, axis=1)

    total_items = len(owned_df)

    # 確保 type 是 Series
    type_data = owned_df[type_col]
    if isinstance(type_data, pd.DataFrame):
        type_series = type_data.iloc[:, 0]
    else:
        type_series = type_data

    types = type_series.dropna().astype(str).str.strip()
    type_count = types.nunique()
    type_dist = types.value_counts().rename_axis("type").reset_index(name="count")

    return total_items, owned_df, type_count, type_dist, owner_cols


def all_people_rank(df, owner_cols):
    """
    多人排行：
    - 每朵花用 extract_unique_names_from_row → 去重
    - 但跨花朵仍然累加（同人拿多朵花會多次計數）
    """
    owner_df = df[owner_cols]
    flat = []
    for _, row in owner_df.iterrows():
        names = extract_unique_names_from_row(row)
        flat.extend(names)

    if not flat:
        return pd.DataFrame(columns=["name", "count"])

    rank = pd.Series(flat).value_counts()
    rank_df = rank.reset_index()
    rank_df.columns = ["name", "count"]
    return rank_df


def get_all_names(df, owner_cols):
    """
    所有出現過的名單（已 canonical + 去重）
    """
    owner_df = df[owner_cols]
    names_set = set()
    for _, row in owner_df.iterrows():
        names = extract_unique_names_from_row(row)
        names_set.update(names)

    names = sorted(names_set)
    return names


def render_harvest_grid(
    used_cells: int,
    view_mode: str = "俯視 (2D)",
    elev: int | None = None,
    azim: int | None = None,
):
    """
    依 TASK_GRID_LAYOUT 畫出格子：
    - 0 ~ used_cells 的格子亮綠燈
    - 其他有效格白底
    - X / None 的位置顯示成灰色
    - 不顯示任何數字，只用顏色表示
    view_mode: "俯視 (2D)" 或 "斜視 (3D)"
    """
    total_cells = 64
    n = max(0, min(int(used_cells), total_cells - 1))

    n_rows = len(TASK_GRID_LAYOUT)
    n_cols = len(TASK_GRID_LAYOUT[0])

    # ---------- 2D 俯視 ----------
    if view_mode == "俯視 (2D)":
        fig, ax = plt.subplots(figsize=(n_cols * 0.7, n_rows * 0.7))
        ax.set_xlim(0, n_cols)
        ax.set_ylim(0, n_rows)
        ax.invert_yaxis()        # 讓第 0 列在最上面
        ax.set_aspect("equal")
        ax.axis("off")

        for r, row in enumerate(TASK_GRID_LAYOUT):
            for c, val in enumerate(row):
                if val is None:          # X 的位置
                    color_grid = "#f0f0f0"    # 淺灰色
                    color_grid = 'none'       # 無色
                    color_edge = 'none'
                else:
                    color_edge = 'black'
                    v = int(val)
                    if v <= n:
                        color_grid = "lightgreen"  # 已使用：綠燈
                    else:
                        color_grid = "white"       # 未使用：白底

                rect = plt.Rectangle(
                    (c, r), 1, 1,
                    facecolor=color_grid,
                    edgecolor=color_edge,
                    linewidth=1,
                )
                ax.add_patch(rect)

        st.pyplot(fig)
        return

    # ---------- 3D 斜視 ----------
    fig = plt.figure(figsize=(n_cols * 0.7, n_rows * 0.7))
    ax = fig.add_subplot(111, projection="3d")

    # 預設視角
    if elev is None:
        elev = 60
    if azim is None:
        azim = -60
    ax.view_init(elev=elev, azim=azim)

    ax.set_xlim(0, n_cols)
    ax.set_ylim(n_rows, 0)   # 反轉 Y 讓上排在畫面上方
    ax.set_zlim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_zticks([])
    ax.set_box_aspect((n_cols, n_rows, 1))  # 比例好看一點

    for r, row in enumerate(TASK_GRID_LAYOUT):
        for c, val in enumerate(row):
            if val is None:
                # color_grid = "#f0f0f0"     # X 的位置：灰色小磚塊
                color_grid = None
                color_edge = None
                color_alpha = 0
                height = 0.01
            else:
                color_edge = 'grey'
                color_alpha = 1
                v = int(val)
                if v <= n:
                    color_grid = "lightgreen"   # 已使用：綠色小方塊
                else:
                    color_grid = "yellow"        # 未使用：白色平台
                height = 0.1

            # 畫一個 3D 小方塊 / 平台
            ax.bar3d(
                c, r, 0,          # x, y, z 底座
                1, 1, height,     # dx, dy, dz
                shade=True,
                color=color_grid,
                edgecolor=color_edge,
                alpha=color_alpha,
                linewidth=0.5,
            )

    ax.axis("off")
    st.pyplot(fig)

# ---------- 各頁面渲染函式 ----------
def page_raw_table(df):
    st.subheader("🌺 花名冊")
    st.dataframe(df_with_flower_index(df), use_container_width=True, height=500)
    st.caption("🌿 點擊表格欄位名稱可依該欄位進行排序。")
    st.markdown(
        """
        - 此頁顯示 Google Sheet 原始內容（名單會在統計時做 s10.xxx 格式與去重處理）。
        - 其他功能頁面會在此基礎上做統計與篩選。
        """
    )


def page_item_owner_counts(items_with_counts):
    st.subheader("🌼 每種花花擁有人數")

    METHOD_COL = "獲得方式"
    GRADE_COL = "品"  # ✅ 新增：品級欄位名稱

    # 取得所有出現過的「獲得方式」原始值（去掉空白）
    method_series = (
        items_with_counts[METHOD_COL]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    method_values_raw = sorted(set([m for m in method_series.unique() if m]))

    # 將「數字 + 等」的項目分組成「等級」一個選項
    level_pattern = re.compile(r"^\d+等$")
    level_methods = [m for m in method_values_raw if level_pattern.match(m)]
    normal_methods = [m for m in method_values_raw if m not in level_methods]

    LEVEL_LABEL = "等級（1等/5等…）"

    method_options = normal_methods.copy()
    if level_methods:
        method_options.append(LEVEL_LABEL)

    # 🔎 搜尋 + 獲得方式篩選
    kw = st.text_input("搜尋花花（可使用關鍵字）", value="")

    mode = st.selectbox(
        "獲得方式篩選",
        ["全部", "自訂 (可多選)"],
        index=0,
        help="選『全部』等於所有獲得方式都包含；選『自訂』可勾單項/多項"
    )

    selected_methods = method_options
    if mode == "自訂 (可多選)":
        selected_methods = st.multiselect(
            "選擇要保留的獲得方式",
            options=method_options,
            default=method_options,
        )

    # ✅ 新增：品級篩選
    grade_options = []
    selected_grades = []
    if GRADE_COL in items_with_counts.columns:
        grade_series = (
            items_with_counts[GRADE_COL]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        grade_options = sorted(set([g for g in grade_series.unique() if g]))
        if grade_options:
            selected_grades = st.multiselect(
                "品級篩選（可多選）",
                options=grade_options,
                default=grade_options,
            )

    # 從完整統計表開始做過濾
    show_df_1 = items_with_counts.copy()

    # 1) 關鍵字搜尋（用 item_desc）
    if kw.strip():
        show_df_1 = show_df_1[
            show_df_1["item_desc"].str.contains(kw, case=False, na=False)
        ]

    # 2) 依獲得方式篩選
    if selected_methods and set(selected_methods) != set(method_options):
        method_clean = (
            show_df_1[METHOD_COL]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        mask = pd.Series(False, index=show_df_1.index)

        for opt in selected_methods:
            if opt == LEVEL_LABEL and level_methods:
                mask |= method_clean.str.match(level_pattern)
            else:
                mask |= (method_clean == opt)

        show_df_1 = show_df_1[mask]

    # 3) 依品級篩選
    if grade_options and selected_grades and set(selected_grades) != set(grade_options):
        grade_clean = (
            show_df_1[GRADE_COL]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        show_df_1 = show_df_1[grade_clean.isin(selected_grades)]

    # 顯示欄位（不顯示 item_desc）
    display_cols = DESC_COLS + ["owner_count", "owners"]

    # ✅ 預設用 owner_count 由少到多排序（不再顯示排序控制）
    show_df_1 = show_df_1.sort_values(
        by="owner_count",
        ascending=True,
        kind="mergesort",
    ).reset_index(drop=True)

    st.dataframe(
        df_with_flower_index(show_df_1[display_cols]),
        use_container_width=True
    )



def page_person_stats(df, owner_cols, items_with_counts):
    st.subheader("🌹 個人花圃")

    all_names = get_all_names(df, owner_cols)
    person_name = st.selectbox("選擇人員(可用關鍵字搜尋)", [""] + all_names)

    if not person_name:
        st.info("選一個花農就會顯示他擁有的花及待蒐集的花。")
        return

    # 既有：這個人已經擁有的統計
    total_items, owned_df, type_count, type_dist, _ = person_stats(
        df, person_name, TYPE_COL, DESC_COLS, OWNER_START_COL
    )

    # 只看「花名」的種類數（TYPE_COL 現在就是「花名」）
    c1, _ = st.columns(2)
    c1.metric("擁有花種數", type_count)

    # 🔁 總共3個tab
    tab1, tab2, tab3 = st.tabs(
        ["🌼 " + person_name + " 的花名冊...", "🌺 等待下架的花...", "🛒 找誰買花"]
    )

    # ---------- Tab 1：已擁有清單 ----------
    with tab1:
        st.subheader("🌼 個人花名冊")
        kw2 = st.text_input("🔍 搜尋此人擁有的花", value="", key="kw2")

        # 先用一個工作用 DataFrame（保留 item_desc 給搜尋用）
        owned_work = owned_df.copy()

        # ⭐ 加入該花的總擁有人數 owner_count & 全部擁有人 owners
        extra_cols = []
        for c in ["owner_count", "owners"]:
            if c in items_with_counts.columns:
                extra_cols.append(c)

        if extra_cols:
            # 用 index 對齊（items_with_counts 與 df 同 index，owned_df 也是用 df.loc[...] 來的）
            extra = items_with_counts[extra_cols].reindex(owned_work.index)
            for c in extra_cols:
                owned_work[c] = extra[c].values

        # 🔍 用 item_desc 做關鍵字搜尋，但 item_desc 不會顯示在表格中
        if kw2.strip():
            owned_work = owned_work[
                owned_work["item_desc"].str.contains(kw2, case=False, na=False)
            ]

        # 顯示用 DataFrame：把 item_desc 拿掉再顯示
        owned_df_show = owned_work.copy()
        if "item_desc" in owned_df_show.columns:
            owned_df_show = owned_df_show.drop(columns=["item_desc"])

        owned_df_show.columns = make_unique_columns(list(owned_df_show.columns))

        if owned_df_show.empty:
            st.info(f"{person_name} 沒有符合搜尋條件的物品。")
        else:
            sort_col_2 = st.selectbox(
                "清單排序欄位",
                options=list(owned_df_show.columns),
                index=0
            )
            asc_2 = st.toggle("清單升冪排序（小→大）", value=True, key="asc2")

            owned_df_show = owned_df_show.sort_values(
                by=sort_col_2, ascending=asc_2, kind="mergesort"
            ).reset_index(drop=True)

            st.dataframe(
                df_with_flower_index(owned_df_show),
                use_container_width=True,
                height=400
            )

    # ---------- Tab 2：我需要的酷東西（還沒拿到的花） ----------
    with tab2:
        st.subheader("🌺 待領取花名冊")

        # 先算出這個人「沒有」的那幾朵花
        owner_df = df[owner_cols]
        unique_names_series = owner_df.apply(extract_unique_names_from_row, axis=1)

        has_person = unique_names_series.apply(lambda names: person_name in names)

        safe_cols = []
        for c in DESC_COLS + [TYPE_COL]:
            if c not in safe_cols:
                safe_cols.append(c)

        missing_df = df.loc[~has_person, safe_cols].copy()
        missing_df["item_desc"] = missing_df[DESC_COLS].astype(str).agg(" | ".join, axis=1)

        # ⭐ 加入 owner_count & owners（這朵花目前有幾個人、是誰有）
        extra_cols = []
        for c in ["owner_count", "owners"]:
            if c in items_with_counts.columns:
                extra_cols.append(c)

        if extra_cols:
            extra = items_with_counts[extra_cols].reindex(missing_df.index)
            for c in extra_cols:
                missing_df[c] = extra[c].values

        miss_total = len(missing_df)
        type_data = missing_df[TYPE_COL]
        if isinstance(type_data, pd.DataFrame):
            type_series = type_data.iloc[:, 0]
        else:
            type_series = type_data
        miss_type_count = (
            type_series.dropna().astype(str).str.strip().nunique()
            if miss_total > 0 else 0
        )

        c3, _ = st.columns(2)
        c3.metric("還沒拿到的花種數", miss_type_count)

        kw3 = st.text_input("🔍 搜尋還沒有拿到的花", value="", key="kw3")

        # 一樣先用工作 DataFrame 搜尋，最後再把 item_desc 拿掉
        missing_work = missing_df.copy()
        if kw3.strip():
            missing_work = missing_work[
                missing_work["item_desc"].str.contains(kw3, case=False, na=False)
            ]

        if missing_work.empty:
            st.info("目前沒有符合條件的『還沒拿到的花』，或是被搜尋條件排掉了。")
        else:
            missing_df_show = missing_work.copy()
            if "item_desc" in missing_df_show.columns:
                missing_df_show = missing_df_show.drop(columns=["item_desc"])

            sort_cols_candidates = list(missing_df_show.columns)
            default_sort_idx = sort_cols_candidates.index("花名") if "花名" in sort_cols_candidates else 0

            sort_col_3 = st.selectbox(
                "未取得清單排序欄位",
                options=sort_cols_candidates,
                index=default_sort_idx,
                key="missing_sort",
            )
            asc_3 = st.toggle(
                "未取得清單升冪排序（小→大）",
                value=True,
                key="missing_asc",
            )

            missing_df_show = missing_df_show.sort_values(
                by=sort_col_3,
                ascending=asc_3,
                kind="mergesort",
            ).reset_index(drop=True)

            st.dataframe(
                df_with_flower_index(missing_df_show),
                use_container_width=True,
                height=400
            )

    # ---------- Tab 3：找誰買花 ----------
    with tab3:
        st.subheader("🛒 找誰買花(摸一把)")

        # 切換顯示方式：依人名 / 依花名
        mode = st.radio(
            "顯示方式",
            ["依人名", "依花名"],
            horizontal=True,
            key=f"buy_mode_{person_name}",
        )

        # ⭐ 關鍵字篩選器（依模式共用）
        kw_buy = st.text_input(
            "🔍 關鍵字篩選（可輸入花名或花農名稱的一部分）",
            value="",
            key=f"buy_kw_{person_name}",
        ).strip()

        # 準備「每朵花有哪些人擁有」的資訊
        cols = list(df.columns)
        start_idx = cols.index(OWNER_START_COL)
        owner_cols_all = cols[start_idx:]
        owner_df = df[owner_cols_all]

        # 每列的唯一名單清單（已做格式整理）
        unique_names_series = owner_df.apply(extract_unique_names_from_row, axis=1)

        # 這個人有 / 沒有的花
        has_person = unique_names_series.apply(lambda names: person_name in names)
        not_has_person = ~has_person

        if mode == "依人名":
            # 1️⃣ 依人名：誰擁有我沒有的花？
            st.caption("列出那些令 " + person_name + " 羨慕的花農以及他的小花們。")

            # 所有花農（排除自己）
            all_names = get_all_names(df, owner_cols)
            others = [n for n in all_names if n != person_name]

            rows = []
            for other in others:
                # 條件：other 有 & 我沒有
                mask = unique_names_series.apply(
                    lambda names, o=other: (o in names) and (person_name not in names)
                )
                idxs = unique_names_series.index[mask]

                if len(idxs) == 0:
                    continue

                # 這個人擁有但我沒有的花名清單
                flowers = (
                    df.loc[idxs, TYPE_COL]
                    .dropna()
                    .astype(str)
                    .tolist()
                )

                # 去重（保留順序）
                seen = set()
                uniq_flowers = []
                for f in flowers:
                    if f not in seen:
                        seen.add(f)
                        uniq_flowers.append(f)

                rows.append(
                    {
                        "花農": other,
                        "我沒有的花數量": len(uniq_flowers),
                        "我沒有的花名稱": ", ".join(uniq_flowers),
                    }
                )

            if not rows:
                st.info("目前沒有任何人擁有你沒有的花。")
            else:
                df_people = pd.DataFrame(rows)

                # ⭐ 套用關鍵字篩選（比對花農名稱 & 花名稱字串）
                if kw_buy:
                    mask_kw = (
                        df_people["花農"].astype(str).str.contains(kw_buy, case=False, na=False)
                        | df_people["我沒有的花名稱"].astype(str).str.contains(kw_buy, case=False, na=False)
                    )
                    df_people = df_people[mask_kw]

                if df_people.empty:
                    st.info("關鍵字篩選後沒有符合條件的結果。")
                else:
                    df_people = df_people.sort_values(
                        by="我沒有的花數量",
                        ascending=False,
                        kind="mergesort",
                    ).reset_index(drop=True)
                    st.dataframe(df_people, use_container_width=True)

        else:
            # 2️⃣ 依花名：有哪些我沒有的花，誰有？
            st.caption("列出 " + person_name + " 沒有的花，以及可以去找誰摸摸。")

            idxs = unique_names_series.index[not_has_person]

            if len(idxs) == 0:
                st.info("你是花農霸主，只有別人找你買的份啦 🌸")
            else:
                rows = []
                for idx in idxs:
                    flower_name = df.at[idx, TYPE_COL]
                    owners_here = unique_names_series[idx]

                    # 小心 None / 空
                    if owners_here is None:
                        owners_here = []
                    owners_here = [str(n) for n in owners_here]

                    # 去重保留順序
                    owners_seen = set()
                    owners_ordered = []
                    for o in owners_here:
                        if o not in owners_seen:
                            owners_seen.add(o)
                            owners_ordered.append(o)

                    rows.append(
                        {
                            "花名": str(flower_name),
                            "持有花農數": len(owners_ordered),
                            "花農名單": ", ".join(owners_ordered),
                        }
                    )

                df_flowers = pd.DataFrame(rows)

                # ⭐ 套用關鍵字篩選（比對花名 & 花農串）
                if kw_buy:
                    mask_kw = (
                        df_flowers["花名"].astype(str).str.contains(kw_buy, case=False, na=False)
                        | df_flowers["花農名單"].astype(str).str.contains(kw_buy, case=False, na=False)
                    )
                    df_flowers = df_flowers[mask_kw]

                if df_flowers.empty:
                    st.info("關鍵字篩選後沒有符合條件的結果。")
                else:
                    # 依「持有花農數」多到少排序，方便優先找人買
                    df_flowers = df_flowers.sort_values(
                        by="持有花農數",
                        ascending=False,
                        kind="mergesort",
                    ).reset_index(drop=True)

                    st.dataframe(df_flowers, use_container_width=True)

    # 保留原本的下載功能（下載「已擁有」的統計）
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        owned_df.to_excel(writer, index=False, sheet_name=f"{person_name}_owned_items")
        type_dist.to_excel(writer, index=False, sheet_name=f"{person_name}_type_dist")
    st.download_button(
        "⬇️ 下載此人統計（Excel）",
        data=buf.getvalue(),
        file_name=f"{person_name}_stats.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )



def page_multi_compare(df, owner_cols):
    st.subheader("🌻 花農排行榜")

    rank_df = all_people_rank(df, owner_cols)
    all_names = get_all_names(df, owner_cols)

    tab_rank, tab_multi = st.tabs(["🌹 排行列表", "🌻 多人比較"])

    with tab_rank:
        sort_col = st.selectbox("排行榜排序欄位", options=["count", "name"], index=0)
        asc = st.toggle("升冪排序（小→大）", value=False, key="rankasc")

        rank_df_sorted = rank_df.sort_values(
            by=sort_col, ascending=asc, kind="mergesort"
        ).reset_index(drop=True)
        st.dataframe(rank_df_sorted, use_container_width=True, height=400)

    with tab_multi:
        st.markdown("### 🌻 多人比較")
        multi_names = st.multiselect("選多個人顯示比較", options=all_names, default=[])

        if multi_names:
            comp_rows = []
            for n in multi_names:
                total_items_n, _, type_count_n, _, _ = person_stats(
                    df, n, TYPE_COL, DESC_COLS, OWNER_START_COL
                )
                comp_rows.append({"name": n, "items": total_items_n, "types": type_count_n})

            comp_df = pd.DataFrame(comp_rows).sort_values(
                by="items", ascending=False, kind="mergesort"
            ).reset_index(drop=True)
            st.dataframe(comp_df, use_container_width=True, height=400)
        else:
            st.info("請從上方選擇至少一個人。")


def page_pair_diff(df, items_with_counts, owner_cols):
    st.subheader("💐 花貿服務")

    # 1️⃣ 選擇要比較的花農（多選）
    all_names = get_all_names(df, owner_cols)
    selected_people = st.multiselect(
        "選擇要比較的花農(可用關鍵字搜尋)",
        options=all_names,
        default=[],
        key="flower_trade_people",
    )

    if not selected_people:
        st.info("請先選擇至少一位花農。")
        return

    # 2️⃣ 準備「每朵花有哪些人擁有」的資訊
    cols = list(df.columns)
    start_idx = cols.index(OWNER_START_COL)
    owner_cols_all = cols[start_idx:]
    owner_df = df[owner_cols_all]

    # 每一 row 的唯一名單清單（已 canonical + 去重）
    unique_names_series = owner_df.apply(extract_unique_names_from_row, axis=1)

    # 建立「花 × 人」布林矩陣：True = 這個人有這朵花
    bool_mat = pd.DataFrame(
        {
            person: unique_names_series.apply(lambda names, p=person: p in names)
            for person in selected_people
        }
    )

    # 3️⃣ 個人擁有花數 + 獨有花統計表
    person_unique_flowers = {}  # 🔹 用來記錄每個人的獨有花清單

    summary_rows = []
    for person in selected_people:
        col_series = bool_mat[person]          # 這個人在每朵花上的 True/False
        total_owned = int(col_series.sum())    # 擁有花數（在目前選取的人群中）

        # 「獨有」定義：在這群 selected_people 裡只有這個人有
        if len(selected_people) > 1:
            others = [p for p in selected_people if p != person]
            others_any = bool_mat[others].any(axis=1)
            unique_mask = col_series & ~others_any
        else:
            # 只選一人時，他擁有的花都算「獨有」
            unique_mask = col_series

        unique_idx = bool_mat.index[unique_mask]

        # 找出這些 row 對應的花名（TYPE_COL，通常是「花名」）
        if len(unique_idx) > 0:
            unique_flowers = (
                df.loc[unique_idx, TYPE_COL]
                .dropna()
                .astype(str)
                .tolist()
            )
        else:
            unique_flowers = []

        # 去重（保留順序）
        seen = set()
        unique_flowers_ordered = []
        for f in unique_flowers:
            if f not in seen:
                seen.add(f)
                unique_flowers_ordered.append(f)
        # 🔹 把這個人的獨有花記起來（之後轉成一朵一格用）
        person_unique_flowers[person] = unique_flowers_ordered
        summary_rows.append(
            {
                "花農": person,
                "擁有花數": total_owned,
                "獨有花數量": len(unique_flowers_ordered),
                "獨有花名稱": ", ".join(unique_flowers_ordered),
            }
        )

    summary_df = pd.DataFrame(summary_rows)

    # 4️⃣ 依目前選取的花農，把花分成三種情況
    any_has = bool_mat.any(axis=1)   # 至少一人擁有
    all_has = bool_mat.all(axis=1)   # 所有人都擁有
    none_has = ~any_has              # 都沒人擁有

    tab_summary, tab_matrix, tab_none, tab_all = st.tabs([
        "🌸 推薦交易清單",
        "🌼 交叉對照表",
        "🌱 都沒人擁有的花",
        "🌻 大家都有的花",
    ])

    # -------- Tab 0：花數總表 --------
    with tab_summary:
        st.markdown("### 🌸 個人擁有花數總表（每人欄位＋獨有花往下排列）")
    
        if summary_df.empty:
            st.info("目前沒有任何已選取的花農。")
        else:
            data_by_person = {}
    
            # 先把每個人的欄內容組好：上兩格是數字，下面連續列出獨有花
            for person in selected_people:
                row = summary_df[summary_df["花農"] == person].iloc[0]
    
                col_values = []
                # 前兩格：數字指標
                col_values.append(row["擁有花數"])
                col_values.append(row["獨有花數量"])
    
                # 再往下：這個人的所有獨有花，依順序連續列出
                for f in person_unique_flowers.get(person, []):
                    col_values.append(f)
    
                data_by_person[person] = col_values
    
            # 對齊成為同一高度的表格（短的補空字串在最下面）
            max_len = max(len(v) for v in data_by_person.values())
            for person, values in data_by_person.items():
                if len(values) < max_len:
                    values.extend([""] * (max_len - len(values)))
                    data_by_person[person] = values
    
            # 建 DataFrame：欄 = 人，列 = [擁有花數, 獨有花數量, 獨有花1, 獨有花2, ...]
            transposed_df = pd.DataFrame(data_by_person)
    
            index_labels = ["擁有花數", "獨有花數量"]
            if max_len > 2:
                index_labels += [f"獨有花{i}" for i in range(1, max_len - 1)]
    
            transposed_df.index = index_labels
    
            st.dataframe(
                transposed_df,
                use_container_width=True,
                height=500,
            )


    # -------- Tab 1：目前有的花 × 人員矩陣（只顯示「部分人擁有」的花） --------
    with tab_matrix:
        st.caption("只顯示在目前選取的花農中，部分人擁有的花（至少一人有、但不是所有人都有）。")

        mixed_mask = any_has & ~all_has
        rows_idx = bool_mat.index[mixed_mask]

        if len(rows_idx) == 0:
            st.info("目前沒有任何只由部分人擁有的花（可能是全部都有或全部都沒有）。")
        else:
            # 基本資訊欄（品、花名、獲得方式、備註）
            base_sub = df.loc[rows_idx, DESC_COLS].copy()

            # 建立「人 × 花」差異矩陣（🟢 / 🟡 / 空白）
            matrix_data = {}
            for p in selected_people:
                col_values = []
                for idx in rows_idx:
                    row_flags = {
                        person: bool_mat.at[idx, person]
                        for person in selected_people
                    }
                    if not row_flags[p]:
                        col_values.append("")
                    else:
                        owners_here = [
                            person for person, has_it in row_flags.items() if has_it
                        ]
                        if len(owners_here) == 1:
                            col_values.append("🟢")  # 獨有燈號
                        else:
                            col_values.append("🟡")  # 共有燈號
                matrix_data[p] = col_values

            matrix_df = pd.DataFrame(matrix_data, index=rows_idx)

            combined_df = pd.concat([base_sub, matrix_df], axis=1)

            st.caption("🟢 = 花農獨有；🟡 = 部分花農共同擁有。")
            st.dataframe(
                df_with_flower_index(combined_df),
                use_container_width=True,
                height=500,
            )
            st.caption("🌿 點擊表格欄位名稱可依該欄位進行排序。")

    # -------- Tab 2：都沒人擁有的花列表 --------
    with tab_none:
        st.caption("在目前選取的花農中，完全沒有任何人擁有的花。")
        rows_idx = bool_mat.index[none_has]

        if len(rows_idx) == 0:
            st.info("目前沒有『都沒人擁有』的花。")
        else:
            base_sub = df.loc[rows_idx, DESC_COLS].copy()
            st.dataframe(
                df_with_flower_index(base_sub),
                use_container_width=True,
                height=500,
            )

    # -------- Tab 3：大家都有的花列表 --------
    with tab_all:
        st.caption("在目前選取的花農中，所有人都有擁有的花。")
        rows_idx = bool_mat.index[all_has]

        if len(rows_idx) == 0:
            st.info("目前沒有任何『大家都有』的花。")
        else:
            base_sub = df.loc[rows_idx, DESC_COLS].copy()
            st.dataframe(
                df_with_flower_index(base_sub),
                use_container_width=True,
                height=500,
            )


def page_task_garden_tool():
    st.subheader("🧮 任務計算機")
    st.caption("輸入任務需求，幫你顯示怎麼種最剛好。")

    # st.markdown("#### 1️⃣ 任務相關數字（暫定 num1 ~ num4，之後你可以改名稱）")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        num1_grid = st.number_input("我的花園格子數", min_value=1, max_value=64, step=1, value=1)
    with c2:
        num2_need = st.number_input("目標收成數量", min_value=1, max_value=999999, step=1, value=1)
    with c3:
        num3_round = st.number_input("鮮花收穫次數", min_value=1, max_value=999999, step=1, value=1)
    with c4:    
        num4_quantity = st.number_input("單次收穫數量", min_value=1, max_value=999999, step=1, value=1)

    # st.markdown("#### 2️⃣ 按下按鈕開始計算適合使用的格數")

    # if st.button("▶️ 開始計算", type="primary"):
    # 🔧 這裡是你之後要寫的「運算邏輯」區域
    # -------------------------------------------------
    # TODO: 請用 num1, num2, num3, num4 計算出一個 0~63 的整數 used_cells
    num_need_cells, remainder = divmod(num2_need, num3_round*num4_quantity)
    if remainder != 0:
        num_need_cells += 1
    # 限制在可用格數內
    need_round, used_cells = divmod(int(num_need_cells), num1_grid)
    if used_cells == 0:
        used_cells = num1_grid
    else:
        need_round += 1
    used_cells -= 1
    # -------------------------------------------------
    st.session_state["task_used_cells"] = used_cells

    # st.markdown("#### 3️⃣ 格子視覺化（綠色代表已使用）")

    if "task_used_cells" in st.session_state:
        used_cells = st.session_state["task_used_cells"]
        st.caption(f"總共需種植 **{num_need_cells}** 格 => 實際需要 **{need_round}** 輪，最後一輪種植 **{used_cells+1}** 格")
        
        adjust_mode = 'auto'
        
        if adjust_mode == 'auto':
            elev = 30
            azim = -60
            view_mode = '斜視 (3D)'
        
        else:    
            # 視角選擇 ＋ 滑桿
            view_mode = st.radio(
                "視角",
                ["俯視 (2D)", "斜視 (3D)"],
                horizontal=True,
                key="task_view_mode",
            )
            elev = azim = None
            if view_mode == "斜視 (3D)":
                c1, c2 = st.columns(2)
                with c1:
                    elev = st.slider("視角高度（elev）", min_value=10, max_value=90, value=30)
                with c2:
                    azim = st.slider("水平旋轉角度（azim）", min_value=-180, max_value=180, value=-60)

        render_harvest_grid(used_cells, view_mode=view_mode, elev=elev, azim=azim)
    else:
        st.info("請先輸入數字，然後按下 **開始計算**。")



# ---------- 主程式 ----------
st.set_page_config(
    page_title="花農市場調查局",
    layout="centered",
    initial_sidebar_state="collapsed"
)

st.title("🌸 花農市場調查局")
st.caption("🌿 統計每種花擁有人數、擁有人名列表、指定人員清單、多人比較，並支援搜尋與篩選。")


# 載入固定 Google Sheet（重新整理網頁就會重新執行並讀取）
try:
    df, loaded_at = load_sheet(FIXED_SHEET_URL)
except Exception as e:
    st.error(f"固定 URL 載入失敗：{e}")
    st.stop()

# 欄位防呆檢查
cols = list(df.columns)

if not DESC_COLS or not OWNER_START_COL or not TYPE_COL:
    st.error("固定欄位設定未完成（DESC_COLS / OWNER_START_COL / TYPE_COL）")
    st.stop()

for c in DESC_COLS:
    if c not in cols:
        st.error(f"DESC_COLS 有不存在的欄位：{c}")
        st.stop()
if OWNER_START_COL not in cols:
    st.error(f"OWNER_START_COL 不存在：{OWNER_START_COL}")
    st.stop()
if TYPE_COL not in cols:
    st.error(f"TYPE_COL 不存在：{TYPE_COL}")
    st.stop()

# ✅ 顯示資料最後載入時間
st.caption(f"📅 資料最後載入時間：{loaded_at.strftime('%Y-%m-%d %H:%M:%S')}")

# 預先算好共用統計（這裡已經做了名單 canonical + 去重）
items_with_counts, owner_cols, owners_norm = compute_owner_counts(
    df, DESC_COLS, OWNER_START_COL
)

# 左側功能切換（保留擴充性）
PAGES = {
    "🌺 花名冊": lambda: page_raw_table(df),
    "🌹 個人花圃": lambda: page_person_stats(df, owner_cols, items_with_counts),
    "💐 花貿服務": lambda: page_pair_diff(df, items_with_counts, owner_cols),
    "🌼 名花榜": lambda: page_item_owner_counts(items_with_counts),
    "🧮 任務計算機": lambda: page_task_garden_tool(),  # 👈 第五項
    # "🌻 花農排行榜": lambda: page_multi_compare(df, owner_cols),
}

with st.sidebar:
    st.header("🌷 調查項目")

    # 🔄 資料更新按鈕：清掉 cache，並立刻 rerun 讓上面的 load_sheet 重新抓資料
    if st.button("🔄 資料更新", help="重新從 Google Sheet 抓最新資料"):
        load_sheet.clear()          # 把 st.cache_data 的快取清掉
        st.rerun()     # 立刻重新執行整個 app

    page_label = st.radio(
        "選擇功能頁面",
        options=list(PAGES.keys()),
        index=0,
        label_visibility="collapsed",  # label 還是在，但畫面上隱藏，避免空字串警告
    )

PAGES[page_label]()
