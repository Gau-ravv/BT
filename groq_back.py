from dotenv import load_dotenv
load_dotenv() # Loads .env file for local development

import streamlit as st
import os
from PIL import Image
import gspread
import json
import warnings
import io
from pdf2image import convert_from_bytes
import groq      # New import
import base64    # New import

warnings.filterwarnings('ignore')

# --- Configuration ---

# !! 1. PASTE YOUR GOOGLE SHEET ID HERE
GOOGLE_SHEET_ID = "1Vzb3o4MyexMxK7AWp8ChTW08dBAWwQr-_QXs8tSY8zQ"
# This will be loaded from secrets when deployed
SERVICE_ACCOUNT_FILE = "service_account.json" 

# Configure Groq API
try:
    # For local dev, it reads from .env
    # For Streamlit deployment, it will read from st.secrets
    groq_api_key = os.getenv("GROQ_API_KEY") or st.secrets.get("GROQ_API_KEY")
    if not groq_api_key:
        raise ValueError("GROQ_API_KEY not found. Set it in .env or Streamlit secrets.")
    
    groq_client = groq.Groq(api_key=groq_api_key)

except Exception as e:
    st.error(f"Could not configure Groq. Error: {e}")

# --- AI Functions ---

def get_groq_response(prompt, image_data, user_input):
    """
    Generate a Groq response using the Llama 4 Scout vision model.
    """
    try:
        # 1. Extract image bytes and encode to base64
        image_bytes = image_data[0]["data"]
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        image_media_type = image_data[0]["mime_type"] # e.g., "image/png"

        # 2. Combine prompts
        combined_prompt_text = f"{prompt}\n\n{user_input}"

        # 3. Call the Groq API
        chat_completion = groq_client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": combined_prompt_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{image_media_type};base64,{base64_image}",
                            },
                        },
                    ],
                }
            ],
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            # Use JSON mode for reliable output
            response_format={"type": "json_object"}, 
            max_tokens=4096 
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        st.error(f"Groq API Error: {e}")
        return None


# --- PDF Processing Function (No changes) ---
def process_pdf_to_images(uploaded_file):
    """
    Converts each page of an uploaded PDF into a list of
    image data formats.
    """
    pdf_bytes = uploaded_file.getvalue()
    
    try:
        images = convert_from_bytes(pdf_bytes)
    except Exception as e:
        st.error(f"PDF Conversion Error: {e}")
        st.info("This app may require the 'Poppler' library on your system (see packages.txt for deployment).")
        return []

    image_data_list = []
    
    for i, img in enumerate(images):
        with io.BytesIO() as buf:
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        
        image_parts = [{
            "mime_type": "image/png",
            "data": img_bytes
        }]
        
        image_name = f"{uploaded_file.name}_page_{i+1}"
        image_data_list.append((image_name, image_parts))
        
    return image_data_list

# --- Google Sheets Function (Updated for Streamlit Secrets) ---

def append_to_google_sheet(data_dict, image_name):
    """
    Appends the extracted data as a new row in Google Sheets.
    """
    try:
        # Check if running in Streamlit cloud and use secrets
        if "SERVICE_ACCOUNT_JSON_STR" in st.secrets:
            SERVICE_ACCOUNT_INFO = json.loads(st.secrets["SERVICE_ACCOUNT_JSON_STR"])
            gc = gspread.service_account_from_dict(SERVICE_ACCOUNT_INFO)
        else:
            # Fallback to local file (for local development)
            gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)

        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        worksheet = sh.get_worksheet(0)
        
        qa_headers = [f"QA_Q{i}" for i in range(1, 31)]
        verbal_headers = [f"Verbal_Q{i}" for i in range(1, 31)]
        lr_headers = [f"LR_Q{i}" for i in range(1, 21)] 

        all_headers = ["Image Name", "Name", "Application_No"] + qa_headers + verbal_headers + lr_headers

        first_row_values = worksheet.row_values(1)
        if not first_row_values or first_row_values[0] == "":
            worksheet.append_row(all_headers)
            st.info("Created new header row in Google Sheet.")

        row_data = [image_name]
        row_data.append(data_dict.get("Name", ""))
        row_data.append(data_dict.get("Application_No", ""))

        qa_answers = data_dict.get("Quantitative_Aptitude", {})
        for i in range(1, 31):
            row_data.append(qa_answers.get(str(i), ""))
        
        verbal_answers = data_dict.get("Verbal", {})
        for i in range(1, 31):
            row_data.append(verbal_answers.get(str(i), ""))

        lr_answers = data_dict.get("Logical_Reasoning", {})
        for i in range(1, 21): 
            row_data.append(lr_answers.get(str(i), ""))
            
        worksheet.append_row(row_data)
        
        return True
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"Error: Spreadsheet not found. Check your GOOGLE_SHEET_ID.")
    except gspread.exceptions.APIError as e:
        st.error(f"Google API Error: {e}")
    except Exception as e:
        st.error(f"Failed to write to Google Sheet: {e}")
        st.info("Did you remember to share your Google Sheet with the service account email?")
    return False

# --- Streamlit App ---

st.set_page_config(page_title="Groq Llama 4 Analyzer")
st.header("Groq Llama 4 PhD Exam Script Analyzer 🧾") 

# Prompt is unchanged, it's perfect for JSON mode
input_prompt = """
You are an expert OCR (Optical Character Recognition) tool.
Analyze the provided image of a PhD Written Exam answer script.
Extract the following information:
1.  **Name**: The name written on the script.
2.  **Application No**: The application number written on the script.
3.  **Quantitative Aptitude**: The handwritten answer (A, B, C, or D) for each question from 1 to 30.
4.  **Verbal**: The handwritten answer (A, B, C, or D) for each question from 1 to 30.
5.  **Logical Reasoning**: The handwritten answer (A, B, C, or D) for each question from 1 to 20.

Your output **MUST** be a single, valid JSON object with these top-level keys:
"Name", "Application_No", "Quantitative_Aptitude", "Verbal", "Logical_Reasoning".

For "Quantitative_Aptitude", "Verbal", and "Logical_Reasoning", the values should be nested JSON objects
where the keys are the question numbers (as strings, e.g., "1") and the values are the marked options (as strings, e.g., "A").
If a value is not found or is unclear, return an empty string for that specific field/question.
"""

user_input = "Extract Name, Application No, and all answers as a single JSON object."

uploaded_file = st.file_uploader("Upload an answer script PDF (pdf)...", type=["pdf"])

submit = st.button("Analyze PDF and Append to Sheet")

# --- Main Submit Logic ---
if submit and uploaded_file is not None:
    if GOOGLE_SHEET_ID == "YOUR_SHEET_ID_HERE" or GOOGLE_SHEET_ID == "1Vzb3o4MyexMxK7AWp8ChTW08dBAWwQr-_QXs8tSY8zQ":
        st.error("Please paste your *own* GOOGLE_SHEET_ID into the app.py file first.")
    else:
        try:
            st.info(f"Processing {uploaded_file.name}... This may take a moment.")
            pages_to_process = process_pdf_to_images(uploaded_file)
            
            if not pages_to_process:
                st.error("No pages found in PDF or PDF processing failed. See error above.")
            else:
                st.success(f"Found {len(pages_to_process)} pages to analyze.")
                
                total_pages = len(pages_to_process)
                progress_bar = st.progress(0, text="Starting analysis...")
                
                for i, (image_name, image_data) in enumerate(pages_to_process):
                    
                    page_num = i + 1
                    progress_text = f"Analyzing page {page_num} of {total_pages} ({image_name})..."
                    progress_bar.progress(page_num / total_pages, text=progress_text)
                    
                    with st.spinner(progress_text):
                        st.image(image_data[0]["data"], caption=f"Analyzing: {image_name}")

                        # 3. Get response from Groq
                        response_text = get_groq_response(input_prompt, image_data, user_input)
                        
                        if not response_text:
                            st.error(f"No response from Groq for page {page_num}. Skipping.")
                            continue

                        # 4. Parse JSON (No cleaning needed due to JSON mode)
                        data_dict = json.loads(response_text)
                        
                        # 5. Append this page's data to Google Sheet
                        with st.spinner(f"Appending data for page {page_num} to sheet..."):
                            success = append_to_google_sheet(data_dict, image_name)
                            if success:
                                st.success(f"Appended data for {image_name} to sheet.")
                            else:
                                st.error(f"Failed to append data for {image_name}.")
                
                progress_bar.empty()
                st.balloons()
                st.header("Analysis Complete!")

        except json.JSONDecodeError as e:
            st.error(f"Error: Groq's response for page {page_num} was not valid JSON. Stopping.")
            st.subheader("Raw Groq Output:")
            st.text(response_text)
        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.info("Please ensure your `service_account.json` file (for local) or secrets (for deployment) are correct and you have shared your Google Sheet with the service account email.")
