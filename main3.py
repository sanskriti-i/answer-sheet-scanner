import os
import json
import time
import io
from typing import Optional
import pandas as pd
import streamlit as st
from PIL import Image, ImageEnhance
from pydantic import BaseModel, Field
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

# --- 🛰️ FASTAPI BACKGROUND ROUTER PATCH ---
# This initializes a background server instances on Hugging Face to serve direct URLs
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTTPException
import uvicorn
import threading

# Create a local folder on the Hugging Face server to hold generated Excel files
DOWNLOAD_DIR = "static_downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

api_app = FastAPI()

@api_app.get("/download/{filename}")
def serve_excel_file_via_url(filename: str):
    """Dynamically captures request strings and serves raw downloads to phones cleanly."""
    safe_filepath = os.path.join(DOWNLOAD_DIR, filename)
    if os.path.exists(safe_filepath):
        return FileResponse(
            path=safe_filepath, 
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    raise HTTPException(status_code=404, detail="Requested file not ready or expired.")

def launch_fastapi_thread():
    # Runs FastAPI quietly in the background on local port 8000
    uvicorn.run(api_app, host="0.0.0.0", port=8000, log_level="error")

if "fastapi_active" not in st.session_state:
    threading.Thread(target=launch_fastapi_thread, daemon=True).start()
    st.session_state.fastapi_active = True
# -------------------------------------------

# 🟢 CLEAN DATA STRUCTURE FOR GEMINI STRUCTURED OUTPUTS (ZERO DEFAULTS)
class QuestionRow(BaseModel):
    question_number: str = Field(description="The question number row from 1 to 8")
    part_a_marks: Optional[str] = Field(description="The text written in column a. Use empty string if blank.")
    part_b_marks: Optional[str] = Field(description="The text written in column b. Use empty string if blank.")
    part_c_marks: Optional[str] = Field(description="The text written in column c. Use empty string if blank.")
    part_d_marks: Optional[str] = Field(description="The text written in column d. Use empty string if blank.")
    question_total: Optional[str] = Field(description="The final total written at the end of the row.")

class AdvancedAnswerSheetData(BaseModel):
    student_name: str = Field(description="The full name of the student.")
    roll_number: str = Field(description="The unique roll number of the student.")
    marks_table: list[QuestionRow] = Field(description="List of rows from question 1 to 8.")
    grand_total_marks: str = Field(description="Final total marks, converted to decimal format.")

# 🟢 REINFORCED ALIGNMENT PROMPT
prompt = (
    "You are a meticulous data extraction script processing an exam sheet table grid.\n"
    "Locate the Student Name, Roll Number, and read the Marks Table line by line.\n\n"
    "⚠️ EXTRACTION SANITY PROTOCOL FOR FRACTIONS:\n"
    "- If you see a handwritten structure like '1 ½', it consists of a whole number 1 and a fraction ½. You MUST extract it as '1.5'.\n"
    "- If two fractions are side by side (e.g., '1 ½' and '1 ½'), process them sequentially. Do not merge them or drop the leading 1 from the second fraction.\n"
    "- Look closely at row 1: It features '1 ½' in column a and '1 ½' in column b. You must explicitly output '1.5' for part_a_marks and '1.5' for part_b_marks.\n\n"
    "📊 COLUMN MAPPING RULE:\n"
    "- Column 1 is 'a', Column 2 is 'b', Column 3 is 'c', Column 4 is 'd'.\n"
    "- Do not move values horizontally. If column a is blank and column b contains a mark, leave part_a_marks as \"\" and place the mark in part_b_marks.\n\n"
    "🛑 VERIFICATION MANDATE:\n"
    "Before formatting the final output, verify that the values assigned to columns a, b, c, and d mathematically sum up to the total column score on that row."
)

# 🟢 Streamlit Page Configurations
st.set_page_config(page_title="AI Verification Scanner", page_icon="📝", layout="wide")

# 🚀 CUSTOM CSS INJECTION FOR HIGH-RESOLUTION CAMERA VIEWS
st.markdown(
    """
    <style>
    video {
        image-rendering: -webkit-optimize-contrast !important;
        image-rendering: crisp-edges !important;
    }
    div[data-testid="stCameraInput"] canvas {
        width: 100% !important;
        height: auto !important;
        image-rendering: pixelated !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.title("📝 Student Marks Multi-Scanner with Continuous Saving")
st.write("Scan multiple sheets consecutively, verify them, and compile everything into a single downloadable Excel file.")

# 🟢 Session States to retain data across multiple scans
if "extracted_df" not in st.session_state:
    st.session_state.extracted_df = None
if "meta_data" not in st.session_state:
    st.session_state.meta_data = {}
if "master_data_list" not in st.session_state:
    st.session_state.master_data_list = []

# 🔑 SIDEBAR STEP 1: Force User to Provide Their Own API Key
st.sidebar.markdown("### 🔑 Step 1: Authentication")
user_api_key = st.sidebar.text_input(
    "Enter your Gemini API Key:", 
    type="password", 
    help="Get a free key from Google AI Studio. This key is processed locally and never stored permanently."
)

if not user_api_key:
    st.sidebar.warning("⚠️ Please provide a valid Gemini API Key to unlock the scanner features.")
    st.info("👋 Welcome! To use this scanner app on your device, look at the sidebar on the left, paste your personal Gemini API Key into the input box, and hit Enter.")
    st.stop()
else:
    genai.configure(api_key=user_api_key)
    st.sidebar.success("🔒 API Key locked in for this session.")

# 📁 STEP 2: Let user upload their existing progress file from their device
st.sidebar.write("---")
st.sidebar.markdown("### 📂 Step 2: Existing File (Optional)")
existing_excel_file = st.sidebar.file_uploader(
    "Want to add to an existing sheet? Select it here:", 
    type=["xlsx"]
)

if existing_excel_file is not None and "file_loaded" not in st.session_state:
    try:
        loaded_df = pd.read_excel(existing_excel_file)
        st.session_state.master_data_list = loaded_df.to_dict(orient="records")
        st.session_state.file_loaded = True
        st.sidebar.success(f"Loaded {len(loaded_df)} existing records successfully!")
    except Exception as e:
        st.sidebar.error(f"Error loading file: {e}")

# Sidebar for camera/upload controls
with st.sidebar:
    st.write("---")
    st.header("🎛️ Input Controls")
    source_option = st.radio("Choose Input Method:", ("📤 Upload or Take Photo", "📸 Web Cam Preview"))
    
    raw_image = None
    if source_option == "📤 Upload or Take Photo":
        uploaded_file = st.file_uploader("Choose image or take a clear photo...", type=["jpg", "jpeg", "png", "webp"])
        if uploaded_file is not None:
            raw_image = Image.open(uploaded_file)
    else:
        camera_file = st.camera_input("Align sheet cover inside frame")
        if camera_file is not None:
            raw_image = Image.open(camera_file)

# 🟢 Layout split into 2 columns: Left for Image, Right for Data Processing
col1, col2 = st.columns([1, 1.2])

with col1:
    if raw_image is not None:
        st.image(raw_image, caption="Current Answer Sheet Preview", use_container_width=True)
        
        if st.button("🚀 Step 3: Extract Marks via AI", type="primary"):
            with st.spinner("AI is analyzing handwriting..."):
                try:
                    img = raw_image.copy()
                    if img.width > 1600:
                        w_percent = (1600 / float(img.width))
                        h_size = int((float(img.height) * float(w_percent)))
                        img = img.resize((1600, h_size), Image.Resampling.LANCZOS)
                        
                    img = img.convert("RGB")
                    img = ImageEnhance.Contrast(img).enhance(1.8)
                    img = ImageEnhance.Sharpness(img).enhance(2.0)
                    
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    
                    content_payload = [img, prompt]
                    generation_config = genai.types.GenerationConfig(
                        response_mime_type="application/json", 
                        response_schema=AdvancedAnswerSheetData,
                        temperature=0.1, 
                    )
                    
                    response = None
                    for attempt in range(6):
                        try:
                            response = model.generate_content(content_payload, generation_config=generation_config)
                            break
                        except ResourceExhausted:
                            wait_time = (attempt + 1) * 10
                            st.warning(f"⚠️ Free tier rate limit reached. Clearing server buffer... Retrying in {wait_time} seconds.")
                            time.sleep(wait_time)
                    
                    if response is None:
                        raise Exception("Failed to get response from Gemini API after multiple retry attempts.")
                        
                    raw_json = json.loads(response.text)
                    
                    st.session_state.meta_data = {
                        "Student Name": raw_json.get("student_name", ""),
                        "Roll Number": raw_json.get("roll_number", ""),
                        "Grand Total Sheet": raw_json.get("grand_total_marks", "")
                    }
                    
                    table_rows = []
                    for row in raw_json.get("marks_table", []):
                        q_num = str(row.get("question_number", "")).strip()
                        if q_num and q_num.isdigit():
                            table_rows.append({
                                "Q.No": f"Q{q_num}",
                                "Part A": row.get("part_a_marks") if row.get("part_a_marks") is not None else "",
                                "Part B": row.get("part_b_marks") if row.get("part_b_marks") is not None else "",
                                "Part C": row.get("part_c_marks") if row.get("part_c_marks") is not None else "",
                                "Part D": row.get("part_d_marks") if row.get("part_d_marks") is not None else "",
                                "Total": row.get("question_total") if row.get("question_total") is not None else ""
                            })
                    
                    st.session_state.extracted_df = pd.DataFrame(table_rows)
                    st.success("AI extraction completed! Review data on the right panel.")
                    
                except Exception as e:
                    if "401" in str(e) or "API key" in str(e):
                        st.error("❌ Authentication Failed: The API key you entered is invalid or deactivated. Please check it in the sidebar.")
                    else:
                        st.error(f"Extraction Error: {e}")

with col2:
    if st.session_state.extracted_df is not None:
        st.header("🔍 Step 4: Review & Edit Grid")
        st.info("💡 Review the current student data. Clicking 'Save Row' will add it to your compiled sheet.")
        
        name_val = st.text_input("Student Name:", value=st.session_state.meta_data.get("Student Name"))
        roll_val = st.text_input("Roll Number:", value=st.session_state.meta_data.get("Roll Number"))
        grand_total_val = st.text_input("Calculated Grand Total:", value=st.session_state.meta_data.get("Grand Total Sheet"))
        
        st.write("### 📊 Question-wise Marks Table")
        edited_table_df = st.data_editor(st.session_state.extracted_df, hide_index=True, use_container_width=True)
        
        if st.button("➕ Step 5: Confirm & Append to Sheet List", type="secondary"):
            final_student_row = {
                "Student Name": name_val,
                "Roll Number": roll_val
            }
            
            for _, row in edited_table_df.iterrows():
                q_num_str = str(row["Q.No"]).replace("Q", "")
                final_student_row[f"{q_num_str}a"] = row["Part A"]
                final_student_row[f"{q_num_str}b"] = row["Part B"]
                final_student_row[f"{q_num_str}c"] = row["Part C"]
                final_student_row[f"{q_num_str}d"] = row["Part D"]
                final_student_row[f"Q{q_num_str}_Total"] = row["Total"]
                
            final_student_row["Grand Total Sheet"] = grand_total_val
            
            st.session_state.master_data_list.append(final_student_row)
            st.success(f"🎉 Successfully added row for '{name_val}'!")
            
            st.session_state.extracted_df = None
            st.session_state.meta_data = {}
            st.rerun()

    # 🟢 Session Summary & Export Actions Area
    if len(st.session_state.master_data_list) > 0:
        st.write("---")
        st.header("📊 Compiled Multi-Student Sheet Preview")
        st.write(f"This spreadsheet contains **{len(st.session_state.master_data_list)}** rows accumulated during this session.")
        
        ordered_columns = ["Student Name", "Roll Number"]
        for i in range(1, 9):
            ordered_columns.extend([f"{i}a", f"{i}b", f"{i}c", f"{i}d", f"Q{i}_Total"])
        ordered_columns.append("Grand Total Sheet")
        
        master_df = pd.DataFrame(st.session_state.master_data_list)
        for col in ordered_columns:
            if col not in master_df.columns:
                master_df[col] = ""
        master_df = master_df[ordered_columns]
        
        st.dataframe(master_df, hide_index=True, use_container_width=True)
        
        # --- 💾 MODIFIED EXCEL PREPARATION AREA ---
        filename = "compiled_student_marks.xlsx"
        local_file_path = os.path.join(DOWNLOAD_DIR, filename)
        
        # 1. This writes and saves the file directly into your local server directory
        with pd.ExcelWriter(local_file_path, engine='xlsxwriter') as writer:
            master_df.to_excel(writer, index=False, sheet_name='All Marks')
        
        # 2. Open file as raw data bytes to satisfy the fallback download stream
        with open(local_file_path, "rb") as f:
            excel_bytes = f.read()
            
        buffer = io.BytesIO(excel_bytes)
        # ------------------------------------------
        
        col_dl1, col_dl2 = st.columns([1, 1])
        with col_dl1:
            # Native Streamlit Button (PC Fallback)
            st.download_button(
                label="📥 Download Compiled Master Excel Sheet",
                data=buffer,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
            
            # --- 📱 MOBILE HTTP ROUTING LINK ---
            # Automatically hooks your running space URL wrapper with your custom download path
            fastapi_url = f"https://xyz-12-answer-sheet-scanner.hf.space/download/{filename}"
            
            mobile_html_link = f'''
            <a href="{fastapi_url}" target="_blank" style="
                background-color: #00cc66; 
                color: white; 
                padding: 10px 20px; 
                text-decoration: none; 
                font-weight: bold; 
                border-radius: 4px; 
                display: inline-block; 
                text-align: center; 
                margin-top: 8px;
                width: 100%;
                box-shadow: 0px 3px 5px rgba(0,0,0,0.15);
            ">📱 Download via Mobile URL (FastAPI)</a>
            '''
            st.markdown(mobile_html_link, unsafe_allow_html=True)
            # ------------------------------------

        with col_dl2:
            if st.button("🗑️ Clear Entire Session Data", type="secondary"):
                st.session_state.master_data_list = []
                if "file_loaded" in st.session_state:
                    del st.session_state.file_loaded
                st.rerun()
                
    elif st.session_state.extracted_df is None:
        st.info("Provide your API key and upload/capture an answer sheet to begin.")
