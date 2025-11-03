# from dotenv import load_dotenv
# load_dotenv()
import streamlit as st
import os
from PIL import Image
import google.generativeai as genai
import gspread
import json
import warnings
import io  # New import
from pdf2image import convert_from_bytes  # New import

warnings.filterwarnings('ignore')
genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])

# --- Configuration ---

# !! 1. PASTE YOUR GOOGLE SHEET ID HERE
GOOGLE_SHEET_ID = "1Vzb3o4MyexMxK7AWp8ChTW08dBAWwQr-_QXs8tSY8zQ"

# !! 2. RENAME YOUR SERVICE ACCOUNT FILE
# SERVICE_ACCOUNT_FILE = "service_account.json"
# We will load the service account from the secret string
SERVICE_ACCOUNT_JSON_STR = st.secrets["SERVICE_ACCOUNT_JSON_STR"]
# Convert the string back into a dictionary
SERVICE_ACCOUNT_INFO = json.loads(SERVICE_ACCOUNT_JSON_STR)


# Configure Gemini API
try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    st.error(f"Could not configure Gemini. Is GOOGLE_API_KEY set? Error: {e}")

# --- Gemini Functions ---

def get_gemini_response(prompt, image_data, user_input):
    """
    Generate a Gemini response using multimodal input (text + image)
    """
    model = genai.GenerativeModel("gemini-2.0-flash-lite") # Using pro-vision for better OCR
    
    response = model.generate_content(
        [user_input, image_data[0], prompt]
    )
    return response.text

# --- NEW: PDF Processing Function ---
def process_pdf_to_images(uploaded_file):
    """
    Converts each page of an uploaded PDF into a list of
    image data formats that Gemini can read.
    Returns a list of tuples: (image_name, image_parts_for_gemini)
    """
    pdf_bytes = uploaded_file.getvalue()
    
    # Convert PDF bytes to a list of PIL Images
    try:
        images = convert_from_bytes(pdf_bytes)
    except Exception as e:
        st.error(f"PDF Conversion Error: {e}")
        st.info("This app will not work until you install the 'Poppler' library on your system. See instructions.")
        return []

    image_data_list = []
    
    for i, img in enumerate(images):
        # Convert PIL Image to bytes (PNG format)
        with io.BytesIO() as buf:
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()
        
        # Create the image_parts dict for Gemini
        image_parts = [{
            "mime_type": "image/png",
            "data": img_bytes
        }]
        
        # Create a descriptive name for the sheet
        image_name = f"{uploaded_file.name}_page_{i+1}"
        
        image_data_list.append((image_name, image_parts))
        
    return image_data_list

# --- Google Sheets Function (No changes) ---

def append_to_google_sheet(data_dict, image_name):
    """
    Appends the extracted data as a new row in Google Sheets.
    """
    try:
        # gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
        gc = gspread.service_account_from_dict(SERVICE_ACCOUNT_INFO)
        sh = gc.open_by_key(GOOGLE_SHEET_ID)
        worksheet = sh.get_worksheet(0)
        
        # Define expected headers for the sheet
        qa_headers = [f"QA_Q{i}" for i in range(1, 31)]
        verbal_headers = [f"Verbal_Q{i}" for i in range(1, 31)]
        lr_headers = [f"LR_Q{i}" for i in range(1, 21)] # Logical Reasoning has 20 questions

        all_headers = ["Image Name", "Name", "Application_No"] + qa_headers + verbal_headers + lr_headers

        # Check if the header row exists or is empty, and create if necessary
        first_row_values = worksheet.row_values(1)
        if not first_row_values or first_row_values[0] == "": # if row is empty or first cell is empty
            worksheet.append_row(all_headers)
            st.info("Created new header row in Google Sheet.")

        # Prepare the data row
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

st.set_page_config(page_title="Gemini Exam Script Analyzer")
st.header("Gemini PhD Exam Script Analyzer 🧾")

# Prompt is unchanged
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

Example JSON structure:
{
  "Name": "John Doe",
  "Application_No": "12345",
  "Quantitative_Aptitude": {
    "1": "A",
    "2": "B",
    ...
  },
  "Verbal": {
    "1": "C",
    ...
  },
  "Logical_Reasoning": {
    "1": "D",
    ...
  }
}
"""

user_input = "Extract Name, Application No, and all answers as a single JSON object."

# --- MODIFIED: File Uploader ---
uploaded_file = st.file_uploader("Upload an answer script PDF (pdf)...", type=["pdf"])

# Image preview is removed since it's a PDF
# if uploaded_file is not None:
#     image = Image.open(uploaded_file)
#     st.image(image, caption="Uploaded Image", use_container_width=True)

submit = st.button("Analyze PDF and Append to Sheet")

# --- MODIFIED: Main Submit Logic ---
if submit and uploaded_file is not None:
    if GOOGLE_SHEET_ID == "YOUR_SHEET_ID_HERE":
        st.error("Please paste your GOOGLE_SHEET_ID into the app.py file first.")
    else:
        try:
            # 1. Process the PDF into a list of images
            st.info(f"Processing {uploaded_file.name}... This may take a moment.")
            pages_to_process = process_pdf_to_images(uploaded_file)
            
            if not pages_to_process:
                st.error("No pages found in PDF or PDF processing failed. See error above.")
            else:
                st.success(f"Found {len(pages_to_process)} pages to analyze.")
                
                total_pages = len(pages_to_process)
                progress_bar = st.progress(0, text="Starting analysis...")
                
                # 2. Loop through each page, analyze, and append
                for i, (image_name, image_data) in enumerate(pages_to_process):
                    
                    page_num = i + 1
                    progress_text = f"Analyzing page {page_num} of {total_pages} ({image_name})..."
                    progress_bar.progress(page_num / total_pages, text=progress_text)
                    
                    with st.spinner(progress_text):
                        # Display the image being processed
                        st.image(image_data[0]["data"], caption=f"Analyzing: {image_name}")

                        # 3. Get response from Gemini for this page
                        response_text = get_gemini_response(input_prompt, image_data, user_input)
                        
                        # Clean and parse JSON
                        clean_response = response_text.strip().replace("```json", "").replace("```", "")
                        data_dict = json.loads(clean_response)
                        
                        # 4. Append this page's data to Google Sheet
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
            st.error(f"Error: Gemini's response for page {page_num} was not in the expected JSON format. Stopping.")
            st.subheader("Raw Gemini Output:")
            st.text(response_text)
        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.info("Please ensure your `service_account.json` file is present and you have shared your Google Sheet with the service account email.")
            
            
# from dotenv import load_dotenv
# load_dotenv()
# import streamlit as st
# import os
# from PIL import Image
# import google.generativeai as genai
# import gspread
# import json
# import warnings

# warnings.filterwarnings('ignore')

# # --- Configuration ---

# # !! 1. PASTE YOUR GOOGLE SHEET ID HERE
# # You can get this from your sheet's URL:
# # https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit
# GOOGLE_SHEET_ID = "1Vzb3o4MyexMxK7AWp8ChTW08dBAWwQr-_QXs8tSY8zQ"

# # !! 2. RENAME YOUR SERVICE ACCOUNT FILE
# # This is the JSON file you downloaded from Google Cloud
# SERVICE_ACCOUNT_FILE = "service_account.json"

# # Configure Gemini API
# try:
#     genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
# except Exception as e:
#     st.error(f"Could not configure Gemini. Is GOOGLE_API_KEY set? Error: {e}")

# # --- Gemini Functions ---

# def get_gemini_response(prompt, image_data, user_input):
#     """
#     Generate a Gemini response using multimodal input (text + image)
#     """
#     model = genai.GenerativeModel("gemini-2.0-flash-lite") 
    
#     response = model.generate_content(
#         [user_input, image_data[0], prompt]
#     )
#     return response.text

# def input_image_setup(uploaded_file):
#     if uploaded_file is not None:
#         bytes_data = uploaded_file.getvalue()
#         image_parts = [
#             {
#                 "mime_type": uploaded_file.type,
#                 "data": bytes_data
#             }
#         ]
#         return image_parts
#     else:
#         raise FileNotFoundError("No file uploaded")

# # --- Google Sheets Function ---

# def append_to_google_sheet(data_dict, image_name):
#     """
#     Appends the extracted data as a new row in Google Sheets.
#     Expects data_dict to have specific keys: "Name", "Application_No",
#     "Quantitative_Aptitude", "Verbal", "Logical_Reasoning".
#     """
#     try:
#         gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
#         sh = gc.open_by_key(GOOGLE_SHEET_ID)
#         worksheet = sh.get_worksheet(0)
        
#         # Define expected headers for the sheet
#         qa_headers = [f"QA_Q{i}" for i in range(1, 31)]
#         verbal_headers = [f"Verbal_Q{i}" for i in range(1, 31)]
#         lr_headers = [f"LR_Q{i}" for i in range(1, 21)] # Logical Reasoning has 20 questions

#         all_headers = ["Image Name", "Name", "Application_No"] + qa_headers + verbal_headers + lr_headers

#         # Check if the header row exists or is empty, and create if necessary
#         # Fetching all values in the first row to check if it's "empty enough"
#         first_row_values = worksheet.row_values(1)
#         if not first_row_values or first_row_values[0] == "": # if row is empty or first cell is empty
#             worksheet.append_row(all_headers)
#             st.info("Created new header row in Google Sheet.")

#         # Prepare the data row
#         row_data = [image_name]
        
#         # Add Name and Application No
#         row_data.append(data_dict.get("Name", ""))
#         row_data.append(data_dict.get("Application_No", ""))

#         # Add Quantitative Aptitude answers (30 questions)
#         qa_answers = data_dict.get("Quantitative_Aptitude", {})
#         for i in range(1, 31):
#             row_data.append(qa_answers.get(str(i), ""))
        
#         # Add Verbal answers (30 questions)
#         verbal_answers = data_dict.get("Verbal", {})
#         for i in range(1, 31):
#             row_data.append(verbal_answers.get(str(i), ""))

#         # Add Logical Reasoning answers (20 questions)
#         lr_answers = data_dict.get("Logical_Reasoning", {})
#         for i in range(1, 21): # Only 20 questions for Logical Reasoning
#             row_data.append(lr_answers.get(str(i), ""))
            
#         # Append the new row to the sheet
#         worksheet.append_row(row_data)
        
#         return True
#     except gspread.exceptions.SpreadsheetNotFound:
#         st.error(f"Error: Spreadsheet not found. Check your GOOGLE_SHEET_ID.")
#     except gspread.exceptions.APIError as e:
#         st.error(f"Google API Error: {e}")
#     except Exception as e:
#         st.error(f"Failed to write to Google Sheet: {e}")
#         st.info("Did you remember to share your Google Sheet with the service account email?")
#     return False

# # --- Streamlit App ---

# st.set_page_config(page_title="Gemini Exam Script Analyzer")

# st.header("Gemini PhD Exam Script Analyzer 🧾")

# # This prompt is now specifically designed to get JSON output for all sections
# input_prompt = """
# You are an expert OCR (Optical Character Recognition) tool.
# Analyze the provided image of a PhD Written Exam answer script.
# Extract the following information:
# 1.  **Name**: The name written on the script.
# 2.  **Application No**: The application number written on the script.
# 3.  **Quantitative Aptitude**: The handwritten answer (A, B, C, or D) for each question from 1 to 30.
# 4.  **Verbal**: The handwritten answer (A, B, C, or D) for each question from 1 to 30.
# 5.  **Logical Reasoning**: The handwritten answer (A, B, C, or D) for each question from 1 to 20.

# Your output **MUST** be a single, valid JSON object with these top-level keys:
# "Name", "Application_No", "Quantitative_Aptitude", "Verbal", "Logical_Reasoning".

# For "Quantitative_Aptitude", "Verbal", and "Logical_Reasoning", the values should be nested JSON objects
# where the keys are the question numbers (as strings, e.g., "1") and the values are the marked options (as strings, e.g., "A").
# If a value is not found or is unclear, return an empty string for that specific field/question.

# Example JSON structure:
# {
#   "Name": "John Doe",
#   "Application_No": "12345",
#   "Quantitative_Aptitude": {
#     "1": "A",
#     "2": "B",
#     "3": "C",
#     ...
#     "30": "D"
#   },
#   "Verbal": {
#     "1": "C",
#     "2": "A",
#     ...
#     "30": "B"
#   },
#   "Logical_Reasoning": {
#     "1": "D",
#     "2": "B",
#     ...
#     "20": "A"
#   }
# }
# """

# # Hardcoded user input, as the prompt is now fixed
# user_input = "Extract Name, Application No, and all answers as a single JSON object."

# uploaded_file = st.file_uploader("Upload an answer script (jpg, jpeg, png)...", type=["jpg", "jpeg", "png"])
# image = None

# if uploaded_file is not None:
#     image = Image.open(uploaded_file)
#     st.image(image, caption="Uploaded Image", use_container_width=True)

# submit = st.button("Analyze and Append to Sheet")

# if submit and uploaded_file is not None:
#     if GOOGLE_SHEET_ID == "YOUR_SHEET_ID_HERE":
#         st.error("Please paste your GOOGLE_SHEET_ID into the app.py file first.")
#     else:
#         with st.spinner("Analyzing with Gemini..."):
#             try:
#                 image_data = input_image_setup(uploaded_file)
#                 response_text = get_gemini_response(input_prompt, image_data, user_input)
                
#                 st.subheader("Raw Gemini Output:")
#                 st.text(response_text)

#                 clean_response = response_text.strip().replace("```json", "").replace("```", "")
#                 data_dict = json.loads(clean_response)
                
#                 st.subheader("Parsed Data:")
#                 st.json(data_dict)

#                 with st.spinner("Appending to Google Sheet..."):
#                     success = append_to_google_sheet(data_dict, uploaded_file.name)
#                     if success:
#                         st.success("Successfully appended data to your Google Sheet!")
#                         st.balloons()
                
#             except json.JSONDecodeError:
#                 st.error("Error: Gemini's response was not in the expected JSON format. Please refine the prompt or check Gemini's output.")
#             except Exception as e:
#                 st.error(f"An error occurred: {e}")
#                 st.info("Please ensure your `service_account.json` file is present and you have shared your Google Sheet with the service account email.")          
                

