import re
import io
import pandas as pd
import streamlit as st


# =========================================================
# ✅ 固定資料來源 + 固定欄位（朋友不用再填）
# =========================================================
FIXED_SHEET_URL = "https://docs.google.com/spreadsheets/d/1-_towzRVHsn7spZrKNdc00RGNG_3xq8_JQ75sPY9HbI/edit?gid=1203973994#gid=1203973994"

DESC_COLS  = ["品", "花名", "獲得方式", "備註"]  # 描述欄（原 A~D）
OWNER_START_COL = "名字"                        # 擁有人欄第一欄
TYPE_COL = "花名"                               # 種類欄（預設用花名當種類）
# 若你要用「品」當種類，把上一行改成 TYPE_COL="品"
# =========================================================


# ---------- 工具函式 ----------
def google_sheet_to_csv_url(sheet_url: str, gid: str | None = None) -> str:
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
    把同一格可能塞的多個名字拆開：
    支援：、 , ; / 換行 以及多空白
    """
    if not cell:
        return []
    parts = re.split(r"[、,;/\n\r]+|\s{2,}", cell)
    parts = [p.strip() for p in parts if p.strip()]
    return parts


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
    cols = list(df.columns)
    if owner_start_col not in cols:
        raise ValueError(f"找不到 OWNER_START_COL：{owner_start_col}")

    start_idx = cols.index(owner_start_col)
    owner_cols = cols[start_idx:]

    owners_norm = df[owner_cols].applymap(normalize_name)

    # 擁有人數
    owner_count = owners_norm.ne("").sum(axis=1)

    # 擁有人名列表（耐髒版，支援同格多名字）
    def owners_list(row):
        names = []
        for v in row:
            v = normalize_name(v)
            if not v:
                continue
            names.extend(split_names(v))
        # 去重但保序
        seen = set()
        uniq = []
        for n in names:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        return ", ".join(uniq)

    owners_str = owners_norm.apply(owners_list, axis=1)

    out = df.copy()
    out["owner_count"] = owner_count
    out["owners"] = owners_str

    # 合併描述一欄（方便搜尋）
    out["item_desc"] = out[desc_cols].astype(str).agg(" | ".join, axis=1)

    return out, owner_cols, owners_norm


def person_stats(df, person_name, type_col, desc_cols, owner_start_col):
    cols = list(df.columns)
    start_idx = cols.index(owner_start_col)
    owner_cols = cols[start_idx:]

    owners_norm = df[owner_cols].applymap(normalize_name)
    has_person = owners_norm.eq(person_name).any(axis=1)

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
    owners_norm = df[owner_cols].applymap(normalize_name)
    flat = owners_norm.values.ravel()
    flat = [n for n in flat if n]
    if not flat:
        return pd.DataFrame(columns=["name", "count"])
    rank = pd.Series(flat).value_counts()
    rank_df = rank.reset_index()
    rank_df.columns = ["name", "count"]
    return rank_df


def get_all_names(df, owner_cols):
    owners_norm = df[owner_cols].applymap(normalize_name)
    names = pd.unique(owners_norm.values.ravel())
    names = sorted([n for n in names if n])
    return names


# ---------- 各頁面渲染函式 ----------
def page_raw_table(df):
    st.subheader("🧾 原始表格")
    st.dataframe(df, use_container_width=True, height=500)

    st.markdown(
        """
        - 此頁顯示 Google Sheet 原始內容。
        - 其他功能頁面會在此基礎上做統計與篩選。
        """
    )


def page_item_owner_counts(items_with_counts):
    st.subheader("📊 每項物品擁有人數")

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
    level_pattern = re.compile(r"^\d+等$")   # 例如 1等, 5等, 10等 ...
    level_methods = [m for m in method_values_raw if level_pattern.match(m)]
    normal_methods = [m for m in method_values_raw if m not in level_methods]

    LEVEL_LABEL = "等級（1等/5等…）"

    # 最後要給使用者選的選項
    method_options = normal_methods.copy()
    if level_methods:
        method_options.append(LEVEL_LABEL)

    # 上面一列做「搜尋 + 獲得方式模式選取」
    col_search, col_method = st.columns([2, 2])

    with col_search:
        kw = st.text_input("🔍 搜尋物品（可搜描述關鍵字）", value="")

    with col_method:
        mode = st.selectbox(
            "獲得方式篩選模式",
            ["全部", "自訂 (可多選)"],
            index=0,  # 預設「全部」
            help="選『全部』等於所有獲得方式都包含；選『自訂』可勾單項/多項"
        )

        # 預設：全部都選
        selected_methods = method_options

        if mode == "自訂 (可多選)":
            selected_methods = st.multiselect(
                "選擇要保留的獲得方式",
                options=method_options,
                default=method_options,   # 初次進來也是全部勾選
            )

    # 從完整統計表開始做過濾
    show_df_1 = items_with_counts.copy()

    # 1) 關鍵字搜尋（用 item_desc，比對完就不顯示這欄）
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

    # 要在畫面上顯示的欄位：描述欄 + 擁有人數 + 擁有人名
    # 不包含 item_desc
    display_cols = DESC_COLS + ["owner_count", "owners"]

    # 排序
    c_sort, c_dir = st.columns([2, 1])
    with c_sort:
        sort_col_1 = st.selectbox(
            "排序欄位",
            options=display_cols,
            index=display_cols.index("owner_count"),
        )
    with c_dir:
        asc_1 = st.toggle("升冪排序（小→大）", value=False)

    show_df_1 = show_df_1.sort_values(
        by=sort_col_1,
        ascending=asc_1,
        kind="mergesort",
    ).reset_index(drop=True)

    # 表格只顯示描述欄 + 擁有人數 + 擁有人名（沒有 item_desc）
    st.dataframe(show_df_1[display_cols], use_container_width=True)


def page_person_stats(df, owner_cols):
    st.subheader("👤 指定人員擁有統計")

    all_names = get_all_names(df, owner_cols)
    person_name = st.selectbox("選擇人員", [""] + all_names)

    if not person_name:
        st.info("選一個人就會顯示他的擁有清單與種類分布。")
        return

    total_items, owned_df, type_count, type_dist, _ = person_stats(
        df, person_name, TYPE_COL, DESC_COLS, OWNER_START_COL
    )

    c1, c2 = st.columns(2)
    c1.metric("擁有物品總數", total_items)
    c2.metric("擁有種類數", type_count)

    st.subheader("2-1) 擁有的物品清單")

    # 清單搜尋（獨立）
    kw2 = st.text_input("🔍 搜尋此人擁有物品", value="", key="kw2")
    owned_df_show = owned_df.copy()

    # 欄名唯一化避免顯示異常
    owned_df_show.columns = make_unique_columns(list(owned_df_show.columns))

    if kw2.strip():
        owned_df_show = owned_df_show[
            owned_df_show["item_desc"].str.contains(kw2, case=False, na=False)
        ]

    if owned_df_show.empty:
        st.warning(f"{person_name} 沒有符合搜尋條件的物品。")
    else:
        c_sort2, c_dir2 = st.columns([2, 1])
        with c_sort2:
            sort_col_2 = st.selectbox(
                "清單排序欄位",
                options=list(owned_df_show.columns),
                index=0
            )
        with c_dir2:
            asc_2 = st.toggle("清單升冪排序（小→大）", value=True, key="asc2")

        owned_df_show = owned_df_show.sort_values(
            by=sort_col_2, ascending=asc_2, kind="mergesort"
        ).reset_index(drop=True)

        st.dataframe(owned_df_show, use_container_width=True)

    st.subheader("2-2) 每種類分布")
    asc_3 = st.toggle("種類分布升冪排序（小→大）", value=False, key="asc3")
    show_type_dist = type_dist.sort_values(by="count", ascending=asc_3).reset_index(drop=True)
    st.dataframe(show_type_dist, use_container_width=True)

    # 👉 可選：在這頁加「下載此人統計」按鈕
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        owned_df_show.to_excel(writer, index=False, sheet_name=f"{person_name}_owned_items")
        show_type_dist.to_excel(writer, index=False, sheet_name=f"{person_name}_type_dist")
    st.download_button(
        "⬇️ 下載此人統計（Excel）",
        data=buf.getvalue(),
        file_name=f"{person_name}_stats.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def page_multi_compare(df, owner_cols):
    st.subheader("📈 多人比較 / 排行")

    rank_df = all_people_rank(df, owner_cols)
    all_names = get_all_names(df, owner_cols)

    c_rank_sort, c_rank_dir = st.columns([2, 1])
    with c_rank_sort:
        rank_sort_col = st.selectbox("排行榜排序欄位", options=["count", "name"], index=0)
    with c_rank_dir:
        rank_asc = st.toggle("升冪排序（小→大）", value=False, key="rankasc")

    rank_df_sorted = rank_df.sort_values(
        by=rank_sort_col, ascending=rank_asc, kind="mergesort"
    ).reset_index(drop=True)
    st.dataframe(rank_df_sorted, use_container_width=True)

    st.markdown("---")
    st.subheader("多人比較")

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
        st.dataframe(comp_df, use_container_width=True)

def page_pair_diff(df, items_with_counts, owner_cols):
    st.subheader("🔍 兩人差異比較（各自擁有但對方沒有的花）")

    all_names = get_all_names(df, owner_cols)

    colA, colB = st.columns(2)
    with colA:
        person_a = st.selectbox("選擇人物 A", [""] + all_names, key="pairA")
    with colB:
        person_b = st.selectbox("選擇人物 B", [""] + all_names, key="pairB")

    if not person_a or not person_b:
        st.info("請先選擇兩個人。")
        return

    if person_a == person_b:
        st.warning("請選兩個**不同**的人。")
        return

    # 重新取得 owners_norm（用 normalize_name）
    owners_norm = df[owner_cols].applymap(normalize_name)

    def row_has_person(row, person):
        for v in row:
            v = normalize_name(v)
            if not v:
                continue
            names = split_names(v)
            if person in names:
                return True
        return False

    has_a = owners_norm.apply(lambda r: row_has_person(r, person_a), axis=1)
    has_b = owners_norm.apply(lambda r: row_has_person(r, person_b), axis=1)

    only_a_mask = has_a & ~has_b
    only_b_mask = has_b & ~has_a

    # 取出 A/B 各自獨有的花（用 items_with_counts 拿 owners/owner_count）
    base_cols = DESC_COLS + ["owner_count", "owners"]
    df_only_a = items_with_counts.loc[only_a_mask, base_cols].copy()
    df_only_b = items_with_counts.loc[only_b_mask, base_cols].copy()

    # 關鍵字搜尋（套在 A、B 兩邊）
    kw = st.text_input("🔍 搜尋關鍵字（品 / 花名 / 獲得方式 / 備註）", value="", key="pair_kw")

    def filter_by_kw(d: pd.DataFrame, kw: str):
        if not kw.strip():
            return d
        kw = kw.strip()
        mask = pd.Series(False, index=d.index)
        for col in DESC_COLS:
            mask |= d[col].astype(str).str.contains(kw, case=False, na=False)
        return d[mask]

    df_only_a = filter_by_kw(df_only_a, kw)
    df_only_b = filter_by_kw(df_only_b, kw)

    # 顯示統計數字
    c_stat_a, c_stat_b = st.columns(2)
    with c_stat_a:
        st.metric(f"{person_a} 獨有花種數", len(df_only_a))
    with c_stat_b:
        st.metric(f"{person_b} 獨有花種數", len(df_only_b))

    st.markdown("---")

    # A / B 兩邊並排顯示表格
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown(f"### 🌸 {person_a} 擁有但 {person_b} 沒有的花")
        if df_only_a.empty:
            st.info(f"{person_a} 沒有任何獨有的花。")
        else:
            sort_col_a = st.selectbox(
                f"{person_a} 排序欄位",
                options=base_cols,
                index=base_cols.index("花名") if "花名" in base_cols else 0,
                key="pair_sortA",
            )
            asc_a = st.toggle("升冪排序（小→大）", value=True, key="pair_ascA")

            df_show_a = df_only_a.sort_values(
                by=sort_col_a,
                ascending=asc_a,
                kind="mergesort",
            ).reset_index(drop=True)

            st.dataframe(df_show_a, use_container_width=True)

    with col_right:
        st.markdown(f"### 🌼 {person_b} 擁有但 {person_a} 沒有的花")
        if df_only_b.empty:
            st.info(f"{person_b} 沒有任何獨有的花。")
        else:
            sort_col_b = st.selectbox(
                f"{person_b} 排序欄位",
                options=base_cols,
                index=base_cols.index("花名") if "花名" in base_cols else 0,
                key="pair_sortB",
            )
            asc_b = st.toggle("升冪排序（小→大）", value=True, key="pair_ascB")

            df_show_b = df_only_b.sort_values(
                by=sort_col_b,
                ascending=asc_b,
                kind="mergesort",
            ).reset_index(drop=True)

            st.dataframe(df_show_b, use_container_width=True)

# ---------- 主程式 ----------
st.set_page_config(page_title="物品擁有統計工具", layout="wide")
st.title("📦 物品擁有統計工具")
st.caption("統計每項物品擁有人數、擁有人名列表、指定人員清單、多人比較，並支援搜尋與篩選。")

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

# 預先算好共用統計
items_with_counts, owner_cols, owners_norm = compute_owner_counts(
    df, DESC_COLS, OWNER_START_COL
)

# 左側功能切換（保留擴充性）
PAGES = {
    "原始表格": lambda: page_raw_table(df),
    "每項物品擁有人數": lambda: page_item_owner_counts(items_with_counts),
    "指定人員擁有統計": lambda: page_person_stats(df, owner_cols),
    "兩人差異比較": lambda: page_pair_diff(df, items_with_counts, owner_cols),
    "多人比較 / 排行": lambda: page_multi_compare(df, owner_cols),
    # 未來擴充：在這裡多加項目即可，例如：
    # "某某新功能": lambda: page_new_feature(df, items_with_counts, owner_cols),
}

with st.sidebar:
    st.header("📂 功能選單")
    page_label = st.radio(
        "選擇功能",
        options=list(PAGES.keys()),
        index=0,
    )

# 根據選擇執行對應頁面
PAGES[page_label]()
