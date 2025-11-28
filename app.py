# -*- coding: utf-8 -*-
"""
Created on Fri Nov 28 11:32:03 2025

@author: delia_chang
"""
import re
import io
import pandas as pd
import streamlit as st


# =========================================================
# ✅ 固定資料來源 + 固定欄位（朋友不用再填）
# =========================================================
FIXED_SHEET_URL = "https://docs.google.com/spreadsheets/d/1-_towzRVHsn7spZrKNdc00RGNG_3xq8_JQ75sPY9HbI/edit?gid=1203973994#gid=1203973994"

DESC_COLS = ["品", "花名", "獲得方式", "備註"]  # 描述欄（原 A~D）
OWNER_START_COL = "名字"                        # 擁有人欄第一欄
TYPE_COL = "花名"                               # 種類欄（預設用花名當種類）
# 若你要用「品」當種類，把上一行改成 TYPE_COL = "品"
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


@st.cache_data(show_spinner=False)
def load_sheet(sheet_url: str) -> pd.DataFrame:
    csv_url = google_sheet_to_csv_url(sheet_url)
    df = pd.read_csv(csv_url)
    return df


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
    owners_norm = owner_df.applymap(normalize_name)

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


# ---------- 各頁面渲染函式 ----------
def page_raw_table(df):
    st.subheader("🌺 花名冊")
    st.dataframe(df_with_flower_index(df), use_container_width=True, height=500)
    st.markdown(
        """
        - 此頁顯示 Google Sheet 原始內容（名單會在統計時做 s10.xxx 格式與去重處理）。
        - 其他功能頁面會在此基礎上做統計與篩選。
        """
    )


def page_item_owner_counts(items_with_counts):
    st.subheader("🌼 每種花花擁有人數")

    METHOD_COL = "獲得方式"

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

    kw = st.text_input("🔍 搜尋物品（可搜描述關鍵字）", value="")

    mode = st.selectbox(
        "獲得方式篩選模式",
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

    show_df_1 = items_with_counts.copy()

    if kw.strip():
        show_df_1 = show_df_1[
            show_df_1["item_desc"].str.contains(kw, case=False, na=False)
        ]

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

    display_cols = DESC_COLS + ["owner_count", "owners"]

    sort_col_1 = st.selectbox(
        "排序欄位",
        options=display_cols,
        index=display_cols.index("owner_count"),
    )
    asc_1 = st.toggle("升冪排序（小→大）", value=False)

    show_df_1 = show_df_1.sort_values(
        by=sort_col_1,
        ascending=asc_1,
        kind="mergesort",
    ).reset_index(drop=True)

    st.dataframe(
        df_with_flower_index(show_df_1[display_cols]),
        use_container_width=True
    )


def page_person_stats(df, owner_cols):
    st.subheader("🌹 個人花圃")

    all_names = get_all_names(df, owner_cols)
    person_name = st.selectbox("選擇人員", [""] + all_names)

    if not person_name:
        st.info("選一個花農就會顯示他擁有的花花跟待下架的酷東西。")
        return

    # 既有：這個人已經擁有的統計
    total_items, owned_df, type_count, type_dist, _ = person_stats(
        df, person_name, TYPE_COL, DESC_COLS, OWNER_START_COL
    )

    # 只看「花名」的種類數（TYPE_COL 現在就是「花名」）
    c1, _ = st.columns(2)
    c1.metric("擁有花種數（依花名）", type_count)


    # 🔁 第二個 tab 改成「我需要的酷東西」
    tab1, tab2 = st.tabs(["🌼 這個花農有...", "🌺 可以考慮再來點..."])

    # ---------- Tab 1：已擁有清單 ----------
    with tab1:
        st.subheader("🌼 個人花名冊")
        kw2 = st.text_input("🔍 搜尋此人擁有物品", value="", key="kw2")
        owned_df_show = owned_df.copy()

        owned_df_show.columns = make_unique_columns(list(owned_df_show.columns))

        if kw2.strip():
            owned_df_show = owned_df_show[
                owned_df_show["item_desc"].str.contains(kw2, case=False, na=False)
            ]

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
        c3.metric("還沒拿到的花（花種數）", miss_type_count)

        kw3 = st.text_input("🔍 搜尋我還沒有拿到的花", value="", key="kw3")
        missing_df_show = missing_df.copy()

        if kw3.strip():
            missing_df_show = missing_df_show[
                missing_df_show["item_desc"].str.contains(kw3, case=False, na=False)
            ]

        if missing_df_show.empty:
            st.info("目前沒有符合條件的『還沒拿到的花』，或是被搜尋條件排掉了。")
        else:
            sort_col_3 = st.selectbox(
                "未取得清單排序欄位",
                options=safe_cols,
                index=safe_cols.index("花名") if "花名" in safe_cols else 0,
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
        "選擇要比較的花農（至少一位）",
        options=all_names,
        default=all_names[:3] if len(all_names) >= 3 else all_names,
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
        "📊 花數總表",
        "🌼 目前有的花 × 人員矩陣",
        "🌱 都沒人擁有的花",
        "🌻 大家都有的花",
    ])

    # -------- Tab 0：花數總表 --------
    with tab_summary:
        st.markdown("### 🌸 個人擁有花數總表")
        st.dataframe(
            summary_df,
            use_container_width=True,
            height=min(400, 40 + 30 * len(summary_df)),
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

            st.caption("🟢 = 在目前選取的花農中，只有該花農擁有；🟡 = 至少有兩位花農共同擁有。")
            st.dataframe(
                df_with_flower_index(combined_df),
                use_container_width=True,
                height=500,
            )

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
    df = load_sheet(FIXED_SHEET_URL)
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

# 預先算好共用統計（這裡已經做了名單 canonical + 去重）
items_with_counts, owner_cols, owners_norm = compute_owner_counts(
    df, DESC_COLS, OWNER_START_COL
)

# 左側功能切換（保留擴充性）
PAGES = {
    "🌺 花名冊": lambda: page_raw_table(df),
    "🌼 花花排行榜": lambda: page_item_owner_counts(items_with_counts),
    "🌹 個人花圃": lambda: page_person_stats(df, owner_cols),
    "💐 花貿服務": lambda: page_pair_diff(df, items_with_counts, owner_cols),
    "🌻 花農排行榜": lambda: page_multi_compare(df, owner_cols),
}

with st.sidebar:
    st.header("🌷 功能選單")
    page_label = st.radio(
        "選擇功能",
        options=list(PAGES.keys()),
        index=0,
    )

PAGES[page_label]()