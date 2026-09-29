import streamlit as st
import pdfplumber
import pypdfium2 as pdfium
from google import genai
from google.genai import types
import re
import pandas as pd
import io
import time

# 1. 頁面配置與高階商務外觀
st.set_page_config(
    page_title="房產精耕謄本助手 Pro",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&family=Noto+Sans+TC:wght@400;500;700&display=swap');
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', 'Noto Sans TC', sans-serif;
    }
    .stApp {
        background: linear-gradient(180deg, #F8FAFC 0%, #F1F5F9 100%);
    }
    .hero-container {
        background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
        border-radius: 16px;
        padding: 30px 36px;
        color: #FFFFFF;
        margin-bottom: 24px;
        box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    .hero-badge {
        display: inline-block;
        background: rgba(14, 165, 233, 0.2);
        color: #38BDF8;
        border: 1px solid rgba(56, 189, 248, 0.3);
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .hero-title {
        font-size: 2.1rem;
        font-weight: 700;
        margin: 0;
        color: #FFFFFF;
    }
    .hero-desc {
        color: #94A3B8;
        font-size: 0.95rem;
        margin-top: 8px;
        margin-bottom: 0;
    }
    [data-testid="stFileUploader"] {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 24px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .stat-card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 18px 22px;
        border: 1px solid #E2E8F0;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
    }
    .stat-label {
        font-size: 0.8rem;
        color: #64748B;
        font-weight: 600;
        text-transform: uppercase;
    }
    .stat-value {
        font-size: 1.7rem;
        font-weight: 700;
        color: #0F172A;
    }
    .stDownloadButton > button {
        background: linear-gradient(135deg, #0EA5E9 0%, #0284C7 100%) !important;
        color: white !important;
        font-weight: 600 !important;
        border-radius: 10px !important;
        border: none !important;
        box-shadow: 0 4px 14px rgba(14, 165, 233, 0.3) !important;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero-container">
    <div class="hero-badge">OPTIMIZED PIPELINE</div>
    <h1 class="hero-title">建物謄本・電傳自動化精耕分析儀</h1>
    <p class="hero-desc">本地高精度解析（姓名去星號、公設坪數持分實算、純車位編號）＋ 專用視覺地址識別。</p>
</div>
""", unsafe_allow_html=True)

# 讀取 API Key (供圖片地址視覺識別備援使用)
api_key = st.secrets.get("GEMINI_API_KEY", "")
if not api_key:
    api_key = st.sidebar.text_input("請輸入 Google Gemini API Key (選填，若有設定可精準解析圖片地址)", type="password")

uploaded_files = st.file_uploader(
    "拖曳或選取謄本 PDF 檔案進行批次萃取",
    type=["pdf"],
    accept_multiple_files=True
)

def extract_address_visual(file_bytes, page_idx=1):
    """ 專門針對第二頁的圖片戶籍地址進行精準視覺識別，徹底過濾頁尾雜訊 """
    if not api_key:
        return "需填APIKey以辨識圖片"
    
    try:
        pdf_doc = pdfium.PdfDocument(file_bytes)
        target_idx = page_idx if len(pdf_doc) > page_idx else len(pdf_doc) - 1
        page = pdf_doc[target_idx]
        
        # 渲染第二頁為圖片
        img = page.render(scale=2.0).to_pil()
        w, h = img.size
        
        # 精準裁切所有權部的中上方（地址所在區域，避開最下方的查詢時間等頁尾）
        crop_area = (int(w * 0.18), int(h * 0.28), int(w * 0.95), int(h * 0.55))
        cropped = img.crop(crop_area)
        
        buf = io.BytesIO()
        cropped.save(buf, format='JPEG', quality=90)
        img_bytes = buf.getvalue()

        client = genai.Client(api_key=api_key)
        prompt = (
            "這張截圖是台灣建物所有權部。請精準讀取「地址」欄位裡的中文地址。"
            "如果該地址有被星號隱匿，請只回覆「隱匿」。"
            "如果是正常地址，請只輸出地址文字，不要輸出「地址：」、不要包含「權利範圍」或頁尾的「查詢時間」等任何其他文字。"
        )

        for _ in range(2):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=[
                        types.Part.from_bytes(data=img_bytes, mime_type='image/jpeg'),
                        prompt
                    ]
                )
                addr_text = response.text.strip().replace("\n", "").replace("`", "")
                addr_text = re.sub(r"^(?:地址|住址)[：:\s]*", "", addr_text)
                
                # 安全過濾：避免抓到頁尾
                if any(k in addr_text for k in ["查詢時間", "資料來源", "登記次序", "權利範圍"]):
                    return "隱匿"
                return addr_text if len(addr_text) > 3 else "隱匿"
            except Exception:
                time.sleep(1.5)
                continue
        return "隱匿"
    except Exception:
        return "隱匿"

def parse_transcript_optimized(file):
    file_bytes = file.read()
    file_stream = io.BytesIO(file_bytes)

    pages_text = []
    with pdfplumber.open(file_stream) as pdf:
        for p in pdf.pages:
            t = p.extract_text()
            pages_text.append(t if t else "")

    full_text = "\n".join(pages_text)

    # 全形轉半形標準化
    half_text = ""
    for char in full_text:
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            half_text += chr(code - 0xFEE0)
        elif code == 0x3000:
            half_text += " "
        else:
            half_text += char

    clean_full = re.sub(r"[\|\t]", " ", half_text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in clean_full.split("\n") if line.strip()]

    data = {
        "建物門牌": "未識別",
        "總坪數": 0.0,
        "主建物(坪)": 0.0,
        "附屬(坪)": 0.0,
        "公設(坪)": 0.0,
        "車位標示": "無/未標示",
        "所有權人": "未識別",
        "戶籍地址": "隱匿"
    }

    # -------------------------------------------------------------
    # 1. 建物完整門牌 (自動補齊 臺南市東區 等)
    # -------------------------------------------------------------
    city_district = ""
    region_match = re.search(r"([^\d\n\r\s]{2,3}(?:市|縣))\s*([^\d\n\r\s]{1,4}(?:區|鄉|鎮|市))", clean_full)
    if region_match:
        city_district = region_match.group(1).replace(" ", "") + region_match.group(2).replace(" ", "")

    raw_doorplate = ""
    for i, line in enumerate(lines):
        if "建物門牌" in line:
            after_label = re.sub(r"^.*?建物門牌[：:\s]*", "", line).strip()
            if len(after_label) > 1:
                raw_doorplate = after_label
                break
            elif i + 1 < len(lines):
                raw_doorplate = lines[i+1].strip()
                break

    raw_doorplate = raw_doorplate.replace(" ", "")
    if raw_doorplate:
        if any(c in raw_doorplate for c in ["市", "縣"]):
            data["建物門牌"] = raw_doorplate
        else:
            if region_match and region_match.group(2) in raw_doorplate:
                data["建物門牌"] = f"{region_match.group(1)}{raw_doorplate}"
            else:
                data["建物門牌"] = f"{city_district}{raw_doorplate}"

    # -------------------------------------------------------------
    # 2. 面積計算：主建、附屬、共有部分持分公設 -> 全部計入總坪數
    # -------------------------------------------------------------
    # 主建物 (層次面積)
    main_m2 = 0.0
    main_match = re.search(r"層次面積\s*([\d\.]+)\s*平方公\s*尺", clean_full)
    if not main_match:
        main_match = re.search(r"層次面積\s*([\d\.]+)", clean_full)
    if main_match:
        main_m2 = float(main_match.group(1))
    data["主建物(坪)"] = round(main_m2 * 0.3025, 2)

    # 附屬建物（陽台、露台、雨遮等加總）
    sub_m2 = 0.0
    sub_matches = re.findall(r"(?:陽台|露台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)\s*平方公\s*尺", clean_full)
    if not sub_matches:
        sub_matches = re.findall(r"(?:陽台|露台|雨遮|平台|花台)[^\d\n\r]*?面積\s*([\d\.]+)", clean_full)
    if sub_matches:
        sub_m2 = sum([float(m) for m in sub_matches])
    data["附屬(坪)"] = round(sub_m2 * 0.3025, 2)

    # 共有部分（公設持分加總：平方公尺前數值 × 權利範圍持分 × 0.3025）
    pub_m2 = 0.0
    shared_section = clean_full
    if "共有部分" in clean_full:
        shared_section = clean_full.split("共有部分")[1]
        if "建物所有權部" in shared_section:
            shared_section = shared_section.split("建物所有權部")[0]
            
    shared_one_line = " ".join(shared_section.split())
    # 抓取「數字 平方公尺 ... 權利範圍 分子 分之 分母」
    pub_items = re.findall(r"([\d\.]+)\s*平方公\s*尺.*?權利範圍\s*(\d+)\s*分之\s*(\d+)", shared_one_line)
    
    for area_str, denom_str, numer_str in pub_items:
        try:
            area_val = float(area_str)
            denom = float(denom_str)
            numer = float(numer_str)
            if denom > 0:
                pub_m2 += area_val * (numer / denom)
        except:
            pass

    data["公設(坪)"] = round(pub_m2 * 0.3025, 2)
    # 總坪數 = 主建 + 附屬 + 公設
    data["總坪數"] = round(data["主建物(坪)"] + data["附屬(坪)"] + data["公設(坪)"], 2)

    # -------------------------------------------------------------
    # 3. 車位標示 (只抓編號，不參考權利範圍)
    # -------------------------------------------------------------
    parking_no = ""
    car_match = re.search(r"(?:含停車位|停車位編號|車位編號|停車位)[：:\s]*([^\n\r，,；;\(（]+)", clean_full)
    if car_match:
        cand = car_match.group(1).strip()
        sub_no = re.search(r"([B|b]?\d+[\s\-]*(?:號)?\d*號?|[B|b]\d+[\-_]\d+)", cand)
        if sub_no:
            floor_m = re.search(r"(地下[一二三四五]層|B[1-5])", cand)
            if floor_m and floor_m.group(1) not in sub_no.group(1):
                parking_no = f"{floor_m.group(1)} {sub_no.group(1)}".strip()
            else:
                parking_no = sub_no.group(1).strip()
        else:
            parking_no = cand

    if not parking_no:
        alt_match = re.search(r"(?:地下[一二三四五]層|B[1-5])[^\d\n\r]*?(\d+[\s\-]*號?|\d+號)", clean_full)
        if alt_match:
            val = alt_match.group(0).strip()
            if not any(k in val for k in ["平方", "民國", "年", "月", "日"]):
                parking_no = val

    if parking_no:
        parking_no = re.sub(r"^(?:含|編號|：|:)+", "", parking_no).strip()
        parking_no = re.split(r"(?:權利範圍|全部|\d+分之\d+)", parking_no)[0].strip()
        data["車位標示"] = parking_no if len(parking_no) > 0 else "無/未標示"
    else:
        data["車位標示"] = "無/未標示"

    # -------------------------------------------------------------
    # 4. 所有權人姓名與性別 (精準穿透排版 + 徹底刪除星號)
    # -------------------------------------------------------------
    owner_sec = clean_full
    owner_page_idx = 1
    for idx, pt in enumerate(pages_text):
        if "所有權" in pt:
            owner_page_idx = idx
            owner_sec = pt
            break

    raw_name = ""
    name_m = re.search(r"所有權人[：:\s\n]*([^\d\n\r\s]+)", owner_sec)
    if name_m:
        # 同時移除半形 '*' 與全形 '＊'
        raw_name = re.sub(r"[\*＊]+", "", name_m.group(1)).strip()

    title = ""
    # 身分證第一碼數字判斷：1 先生、2 女士
    id_m = re.search(r"([A-Za-z])\s*([12])[\d\*＊]{2,}", owner_sec)
    if id_m:
        code = id_m.group(2)
        if code == "1":
            title = "先生"
        elif code == "2":
            title = "女士"

    if raw_name:
        data["所有權人"] = raw_name + title

    # -------------------------------------------------------------
    # 5. 戶籍地址：優先本地文字提取，若為防護圖片則走專用視覺識別
    # -------------------------------------------------------------
    got_text_addr = False
    local_addr_m = re.search(r"(?:地址|住址)[：:\s\n]*([^\n\r]+)", owner_sec)
    if local_addr_m:
        cand = local_addr_m.group(1).strip()
        cand = re.split(r"(?:權利範圍|統一編號|權狀字號)", cand)[0].strip()
        if any(w in cand for w in ["市", "縣", "鄉", "鎮", "區", "路", "街", "巷"]):
            data["戶籍地址"] = cand
            got_text_addr = True

    if not got_text_addr:
        data["戶籍地址"] = extract_address_visual(file_bytes, page_idx=owner_page_idx)

    return data

# 5. 介面呈現與批次處理
if uploaded_files:
    results = []
    with st.spinner("⚡ 正在進行最佳化解析，請稍候..."):
        for f in uploaded_files:
            try:
                info = parse_transcript_optimized(f)
                results.append(info)
            except Exception as e:
                st.error(f"檔案 {f.name} 處理失敗：{e}")

    if results:
        df = pd.DataFrame(results)
        columns_to_show = [
            "建物門牌", "總坪數", "主建物(坪)", "附屬(坪)", "公設(坪)",
            "車位標示", "所有權人", "戶籍地址"
        ]
        df = df[columns_to_show]

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)
        
        # 儀表板
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">已解析戶數</span>
                <span class="stat-value">{len(df)} <span style="font-size: 1rem; color: #64748B;">筆</span></span>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            total_sum = round(df["總坪數"].sum(), 2)
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">總建坪規模</span>
                <span class="stat-value">{total_sum} <span style="font-size: 1rem; color: #64748B;">坪</span></span>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            parking_count = (df["車位標示"] != "無/未標示").sum()
            st.markdown(f"""
            <div class="stat-card">
                <span class="stat-label">具備車位戶數</span>
                <span class="stat-value">{parking_count} <span style="font-size: 1rem; color: #64748B;">筆</span></span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
        
        # 數據總表
        st.dataframe(df, use_container_width=True, height=min(450, 45 + len(df) * 38))

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

        csv_data = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            label="📥 匯出精耕專用名冊 (Excel CSV)",
            data=csv_data,
            file_name="社區精耕謄本整理名冊.csv",
            mime="text/csv"
        )
