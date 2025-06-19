import streamlit as st
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import letter, A4, landscape  
from google.oauth2 import service_account
import io
from datetime import datetime
import numpy as np
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

pdfmetrics.registerFont(TTFont('NotoSansTelugu', './NotoSansTelugu.ttf'))

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = st.secrets.general.id
SHEET_NAMES = ['LIST_CREATION']

# ---------- GOOGLE SHEETS CONNECTION ----------
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_google_sheets_data():
    """Fetch data from Google Sheets with timeout handling"""
    try:
        credentials = service_account.Credentials.from_service_account_info(st.secrets["google_service_account"],scopes=SCOPES)
        service = build('sheets', 'v4', credentials=credentials)
        sheet = service.spreadsheets()
        
        # Fetch data from the sheet with timeout
        result = sheet.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{SHEET_NAMES[0]}!A:L"  # Assuming 12 columns (A to L)
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            st.error("No data found in the sheet")
            return pd.DataFrame()
        
        # Convert to DataFrame
        df = pd.DataFrame(values[1:], columns=values[0])  # First row as header
        
        # Debug: Check Telugu name encoding
        if 'TELUGU NAME' in df.columns:
            st.sidebar.write("**Debug - Telugu Names Sample:**")
            sample_telugu = df['TELUGU NAME'].dropna().head(3).tolist()
            for i, name in enumerate(sample_telugu):
                st.sidebar.write(f"{i+1}. {repr(name)} -> {name}")
        
        return df
        
    except Exception as e:
        st.error(f"Error fetching data from Google Sheets: {str(e)}")
        return pd.DataFrame()

# ---------- DATA PROCESSING FUNCTIONS ----------
def process_data_for_date(df, selected_date):
    """Filter and process data for selected date"""
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    # Convert DATE column to datetime if needed
    try:
        df['DATE'] = pd.to_datetime(df['DATE'], format='%d/%m/%Y', errors='coerce')
        selected_date = pd.to_datetime(selected_date)
        
        # Filter by date
        filtered_df = df[df['DATE'].dt.date == selected_date.date()]
        
        if filtered_df.empty:
            st.warning(f"No data found for date: {selected_date.strftime('%Y-%m-%d')}")
            return pd.DataFrame(), pd.DataFrame()
        
        # Clean and prepare data
        filtered_df.loc[:, 'QUANTITY'] = pd.to_numeric(filtered_df['QUANTITY'], errors='coerce').fillna(0)
        filtered_df = filtered_df[filtered_df['QUANTITY'] > 0]  # Remove zero quantities
        
        return filtered_df, filtered_df
    except Exception as e:
        st.error(f"Error processing data: {str(e)}")
        return pd.DataFrame(), pd.DataFrame()

def create_vegetable_report_data(df):
    """Create data structure for Report 1: Vegetable-wise summary - SORTED ALPHABETICALLY"""
    if df.empty:
        return pd.DataFrame()
    
    # Define the desired hotel order
    desired_hotel_order = ['NOVOTEL', 'GRANDBAY', 'RADISSONBLU', ' BHEEMILI']
    
    available_hotels = df['MAIN HOTEL NAME'].unique()

    # Create ordered list of hotels - first the desired order, then any others alphabetically
    hotels = []
    for hotel in desired_hotel_order:
        if hotel in available_hotels:
            hotels.append(hotel)
    
    # Add any remaining hotels not in the desired order (sorted alphabetically)
    remaining_hotels = sorted([h for h in available_hotels if h not in desired_hotel_order])
    hotels.extend(remaining_hotels)

    
    # Group by PIVOT_VEGETABLE_NAME AND units combination to handle different units properly
    report_data = []
    
    # Get unique combinations of PIVOT_VEGETABLE_NAME and units
    veg_unit_combinations = df[['PIVOT_VEGETABLE_NAME', 'UNITS', 'TELUGU NAME']].drop_duplicates()
    
    for _, row in veg_unit_combinations.iterrows():
        veg_name = row['PIVOT_VEGETABLE_NAME']
        units = row['UNITS']
        telugu_name = row['TELUGU NAME']
        
        # Filter data for this specific vegetable-unit combination
        veg_data = df[(df['PIVOT_VEGETABLE_NAME'] == veg_name) & (df['UNITS'] == units)]
        
        # Create display name that includes units if there are multiple unit types for same vegetable
        veg_units_count = df[df['PIVOT_VEGETABLE_NAME'] == veg_name]['UNITS'].nunique()
        if veg_units_count > 1:
            display_name = f"{veg_name} ({units})"
        else:
            display_name = veg_name
        
        report_row = {
            'PIVOT_VEGETABLE_NAME': display_name,
            'Telugu Name': telugu_name,
        }
        
        total_qty = 0
        
        # Add quantity for each hotel
        for hotel in hotels:
            hotel_data = veg_data[veg_data['MAIN HOTEL NAME'] == hotel]
            qty = hotel_data['QUANTITY'].sum() if not hotel_data.empty else 0
            report_row[f"{hotel}"] = f"{qty} {units}" if qty > 0 else f"0 {units}"
            total_qty += qty
        
        report_row['Total Quantity'] = f"{total_qty} {units}"
        report_data.append(report_row)
    
    # Convert to DataFrame and sort alphabetically by PIVOT_VEGETABLE_NAME
    result_df = pd.DataFrame(report_data)
    if not result_df.empty:
        result_df = result_df.sort_values('PIVOT_VEGETABLE_NAME', ascending=True).reset_index(drop=True)
    
    return result_df

def create_vendor_report_data(df):
    """Create data structure for Report 2: Vendor-wise summary with Telugu names - SORTED ALPHABETICALLY"""
    if df.empty:
        return {}
    
    # Define the desired hotel order
    desired_hotel_order = ['NOVOTEL', 'GRANDBAY', 'RADISSONBLU', ' BHEEMILI']
    
    # Get unique hotels from data
    available_hotels = df['MAIN HOTEL NAME'].unique()
    
    # Create ordered list of hotels - first the desired order, then any others alphabetically
    hotels = []
    for hotel in desired_hotel_order:
        if hotel in available_hotels:
            hotels.append(hotel)
    
    # Add any remaining hotels not in the desired order (sorted alphabetically)
    remaining_hotels = sorted([h for h in available_hotels if h not in desired_hotel_order])
    hotels.extend(remaining_hotels)
    
    vendors = sorted(df['VENDOR'].dropna().unique())  # Sort vendors alphabetically too

    vendor_reports = {}
    
    for vendor in vendors:
        if pd.isna(vendor) or vendor == '':
            continue
            
        vendor_data = df[df['VENDOR'] == vendor]
        vendor_report = []
        
        # Get unique combinations of PIVOT_VEGETABLE_NAME and units for this vendor
        veg_unit_combinations = vendor_data[['PIVOT_VEGETABLE_NAME', 'UNITS', 'TELUGU NAME']].drop_duplicates()
        
        for _, row in veg_unit_combinations.iterrows():
            veg_name = row['PIVOT_VEGETABLE_NAME']
            units = row['UNITS']
            telugu_name = row['TELUGU NAME']
            
            # Filter data for this specific vegetable-unit combination
            veg_data = vendor_data[(vendor_data['PIVOT_VEGETABLE_NAME'] == veg_name) & (vendor_data['UNITS'] == units)]
            
            # Create display name that includes units if there are multiple unit types for same vegetable
            veg_units_count = vendor_data[vendor_data['PIVOT_VEGETABLE_NAME'] == veg_name]['UNITS'].nunique()
            if veg_units_count > 1:
                display_name = f"{veg_name} ({units})"
            else:
                display_name = veg_name
            
            report_row = {
                'PIVOT_VEGETABLE_NAME': display_name,
                'Telugu Name': telugu_name
            }
            total_qty = 0
            
            for hotel in hotels:
                hotel_data = veg_data[veg_data['MAIN HOTEL NAME'] == hotel]
                qty = hotel_data['QUANTITY'].sum() if not hotel_data.empty else 0
                report_row[hotel] = f"{qty} {units}" if qty > 0 else f"0 {units}"
                total_qty += qty
            
            report_row['Total'] = f"{total_qty} {units}"
            vendor_report.append(report_row)
        
        # Convert to DataFrame and sort alphabetically by PIVOT_VEGETABLE_NAME
        vendor_df = pd.DataFrame(vendor_report)
        if not vendor_df.empty:
            vendor_df = vendor_df.sort_values('PIVOT_VEGETABLE_NAME', ascending=True).reset_index(drop=True)
        
        vendor_reports[vendor] = vendor_df
    
    return vendor_reports

# ---------- PDF GENERATION FUNCTIONS ----------
def create_individual_hotel_reports_pdf(df, selected_date):
    """Generate PDF with individual reports for each hotel - one hotel per page"""
    if df.empty:
        return None
        
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []
    
    # Define the desired hotel order
    desired_hotel_order = ['Novotel', 'Grandbay', 'Radisson', 'Bheemili']
    
    # Get unique hotels from data in desired order
    available_hotels = df['MAIN HOTEL NAME'].unique()
    hotels = []
    for hotel in desired_hotel_order:
        if hotel in available_hotels:
            hotels.append(hotel)
    
    # Add any remaining hotels not in the desired order (sorted alphabetically)
    remaining_hotels = sorted([h for h in available_hotels if h not in desired_hotel_order])
    hotels.extend(remaining_hotels)
    
    # Main title page
    title_style = ParagraphStyle(
        'MainTitle',
        parent=styles['Heading1'],
        fontSize=20,
        spaceAfter=30,
        alignment=1,  # Center alignment
        textColor=colors.darkblue
    )
    # main_title = Paragraph(f"Individual Hotel Reports - {selected_date.strftime('%Y-%m-%d')}", title_style)
    # story.append(main_title)
    # story.append(Spacer(1, 30))
    
    # # Add hotel list on title page
    # hotel_list_style = ParagraphStyle(
    #     'HotelList',
    #     parent=styles['Normal'],
    #     fontSize=14,
    #     spaceAfter=10,
    #     alignment=1,
    #     textColor=colors.darkgreen
    # )
    # story.append(Paragraph("Hotels Included in This Report:", hotel_list_style))
    # story.append(Spacer(1, 10))
    
    # for i, hotel in enumerate(hotels, 1):
    #     hotel_item = Paragraph(f"{i}. {hotel}", styles['Normal'])
    #     story.append(hotel_item)
    
    # story.append(PageBreak())
    
    # Generate individual hotel reports
    for hotel_index, hotel in enumerate(hotels):
        # Hotel title
        hotel_title_style = ParagraphStyle(
            'HotelTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=20,
            spaceBefore=10,
            alignment=1,
            textColor=colors.darkblue
        )
        hotel_title = Paragraph(f"Hotel: {hotel}", hotel_title_style)
        story.append(hotel_title)
        
        # Date subtitle
        date_style = ParagraphStyle(
            'DateStyle',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=20,
            alignment=1,
            textColor=colors.grey
        )
        date_subtitle = Paragraph(f"Date: {selected_date.strftime('%Y-%m-%d')}", date_style)
        story.append(date_subtitle)
        
        # Filter data for this hotel
        hotel_data = df[df['MAIN HOTEL NAME'] == hotel]
        
        if hotel_data.empty:
            no_data_style = ParagraphStyle(
                'NoData',
                parent=styles['Normal'],
                fontSize=14,
                alignment=1,
                textColor=colors.red
            )
            story.append(Paragraph("No orders found for this hotel on the selected date.", no_data_style))
        else:
            # Group by vegetable and sum quantities (handling multiple units)
            hotel_report_data = []
            
            # Get unique combinations of PIVOT_VEGETABLE_NAME and units for this hotel
            veg_unit_combinations = hotel_data[['PIVOT_VEGETABLE_NAME', 'UNITS', 'TELUGU NAME']].drop_duplicates()
            
            for _, row in veg_unit_combinations.iterrows():
                veg_name = row['PIVOT_VEGETABLE_NAME']
                units = row['UNITS']
                telugu_name = row['TELUGU NAME']
                
                # Filter data for this specific vegetable-unit combination
                veg_data = hotel_data[(hotel_data['PIVOT_VEGETABLE_NAME'] == veg_name) & (hotel_data['UNITS'] == units)]
                total_qty = veg_data['QUANTITY'].sum()
                
                if total_qty > 0:  # Only include items with quantity > 0
                    # Create display name that includes units if there are multiple unit types for same vegetable
                    veg_units_count = hotel_data[hotel_data['PIVOT_VEGETABLE_NAME'] == veg_name]['UNITS'].nunique()
                    if veg_units_count > 1:
                        display_name = f"{veg_name} ({units})"
                    else:
                        display_name = veg_name
                    
                    hotel_report_data.append([
                        display_name,
                        telugu_name if telugu_name and str(telugu_name) != 'nan' else '',
                        f"{total_qty} {units}"
                    ])
            
            # Sort alphabetically by vegetable name
            hotel_report_data.sort(key=lambda x: x[0])
            
            if hotel_report_data:
                # Create table
                table_data = [['Vegetable Name', 'Telugu Name', 'Quantity']]
                table_data.extend(hotel_report_data)
                
                # Calculate column widths
                available_width = 7 * inch  # A4 width minus margins
                col_widths = [2.5*inch, 2*inch, 2.5*inch]
                
                table = Table(table_data, colWidths=col_widths)
                table.setStyle(TableStyle([
                    # Header styling
                    ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 12),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    
                    # Data rows styling
                    ('FONTNAME', (1, 1), (1, -1), 'NotoSansTelugu'),  # Telugu column
                    ('FONTSIZE', (0, 1), (-1, -1), 10),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ]))
                
                story.append(table)
                
                # Add summary
                story.append(Spacer(1, 20))
                summary_style = ParagraphStyle(
                    'Summary',
                    parent=styles['Normal'],
                    fontSize=11,
                    alignment=1,
                    textColor=colors.darkgreen
                )
                total_items = len(hotel_report_data)
                summary_text = f"Total Items Ordered: {total_items}"
                story.append(Paragraph(summary_text, summary_style))
            else:
                story.append(Paragraph("No items with quantities found for this hotel.", styles['Normal']))
        
        # Add page break after each hotel except the last one
        if hotel_index < len(hotels) - 1:
            story.append(PageBreak())
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer

# ---------- EXISTING PDF GENERATION FUNCTIONS ----------
def create_combined_report_pdf(veg_data, vendor_data, selected_date):
    """Generate SINGLE PDF containing both vegetable and vendor reports with Telugu support"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []
    
    # Main title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=30,
        alignment=1  # Center alignment
    )
    title = Paragraph(f"Complete Order Summary Report - {selected_date.strftime('%Y-%m-%d')}", title_style)
    story.append(title)
    story.append(Spacer(1, 20))
    
    # SECTION 1: VEGETABLE-WISE SUMMARY
    section1_title = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'], 
        fontSize=14,
        spaceAfter=20,
        spaceBefore=10,
        alignment=1,
        textColor=colors.darkblue
    )
    story.append(Paragraph("SECTION 1: VEGETABLE-WISE ORDER SUMMARY", section1_title))
    story.append(Spacer(1, 10))
    
    if veg_data.empty:
        story.append(Paragraph("No vegetable data available for the selected date.", styles['Normal']))
    else:
        # Create table data - handle Telugu text encoding
        table_data = []
        headers = veg_data.columns.tolist()
        table_data.append(headers)
        
        for _, row in veg_data.iterrows():
            row_data = []
            for col in headers:
                cell_value = str(row[col]) if row[col] is not None else ""
                # Handle Telugu text - ensure proper encoding
                if col == 'Telugu Name':
                    try:
                        if cell_value and cell_value != 'nan':
                            cell_value = cell_value.encode('utf-8').decode('utf-8')
                        else:
                            cell_value = ""
                    except:
                        cell_value = ""
                row_data.append(cell_value)
            table_data.append(row_data)
        
        # Create table with adjusted column widths
        available_width = 14.5 * inch  # A4 width minus margins
        num_cols = len(headers)
        if num_cols <= 4:
            col_widths = [available_width/num_cols] * num_cols
        else:
            # Adjust widths for better display
            col_widths = [1.8*inch, 1.2*inch] + [1*inch] * (num_cols - 2)
            if sum(col_widths) > available_width:
                col_widths = [available_width/num_cols] * num_cols
        
        table = Table(table_data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (1, 1), (1, -1), 'NotoSansTelugu'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),  # Header row font size
            ('FONTSIZE', (0, 1), (-1, -1), 10),  # Data rows font size
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        story.append(table)
    
    # Page break before vendor section
    story.append(PageBreak())
    
    # SECTION 2: VENDOR-WISE SUMMARY
    story.append(Paragraph("SECTION 2: VENDOR-WISE ORDER SUMMARY", section1_title))
    story.append(Spacer(1, 20))
    
    if not vendor_data:
        story.append(Paragraph("No vendor data available for the selected date.", styles['Normal']))
    else:
        vendor_names = list(vendor_data.keys())
        for i, (vendor_name, data) in enumerate(vendor_data.items()):
            if i > 0:
                story.append(PageBreak())
            
            # Vendor title
            vendor_title_style = ParagraphStyle(
                'VendorTitle',
                parent=styles['Heading3'],
                fontSize=12,
                spaceAfter=15,
                spaceBefore=10,
                textColor=colors.darkgreen
            )
            vendor_title = Paragraph(f"Vendor: {vendor_name}", vendor_title_style)
            story.append(vendor_title)
            
            # Create table data - handle Telugu text encoding
            table_data = []
            headers = data.columns.tolist()
            table_data.append(headers)
            
            for _, row in data.iterrows():
                row_data = []
                for col in headers:
                    cell_value = str(row[col]) if row[col] is not None else ""
                    # Handle Telugu text - ensure proper encoding
                    if col == 'Telugu Name':
                        try:
                            if cell_value and cell_value != 'nan':
                                cell_value = cell_value.encode('utf-8').decode('utf-8')
                            else:
                                cell_value = ""
                        except:
                            cell_value = ""
                    row_data.append(cell_value)
                table_data.append(row_data)
            
            # Create table with adjusted column widths
            num_cols = len(headers)
            if num_cols <= 4:
                col_widths = [available_width/num_cols] * num_cols
            else:
                col_widths = [1.8*inch, 1.2*inch] + [0.9*inch] * (num_cols - 2)
                if sum(col_widths) > available_width:
                    col_widths = [available_width/num_cols] * num_cols
            
            table = Table(table_data, colWidths=col_widths)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (1, 1), (1, -1), 'NotoSansTelugu'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),  # Header row font size
                ('FONTSIZE', (0, 1), (-1, -1), 10),  # Data rows font size
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            
            story.append(table)
            story.append(Spacer(1, 20))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer

# Simplified synchronous version - no threading
def generate_reports(df, selected_date):
    """Generate reports synchronously to avoid threading issues"""
    try:
        # Process data
        filtered_df, _ = process_data_for_date(df, selected_date)
        
        if filtered_df.empty:
            return None, None, None, None
        
        # Create report data
        veg_report_data = create_vegetable_report_data(filtered_df)
        vendor_report_data = create_vendor_report_data(filtered_df)
        
        # Generate combined PDF
        combined_pdf_buffer = create_combined_report_pdf(veg_report_data, vendor_report_data, selected_date)
        
        # Generate individual hotel reports PDF
        individual_hotel_pdf_buffer = create_individual_hotel_reports_pdf(filtered_df, selected_date)
        
        return veg_report_data, vendor_report_data, combined_pdf_buffer, individual_hotel_pdf_buffer
        
    except Exception as e:
        st.error(f"Error generating reports: {str(e)}")
        return None, None, None, None

def check_password():
    """Simple password authentication"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 Secure Access")
        password = st.text_input("Enter password to access the app:", type="password")
        
        if password == "hotel@79":  # Replace with your password
            st.session_state.authenticated = True
            st.success("✅ Access granted. Loading app...")
            st.rerun()
        elif password != "":
            st.error("❌ Incorrect password")
        return False
    else:
        return True

# ---------- STREAMLIT APP ----------
def main():
    if not check_password():
        return  # Stop app from loading unless authenticated
    
    st.set_page_config(
        page_title="Hotel Order Management System",
        page_icon="🏨",
        layout="wide"
    )
    
    st.title("🏨 Hotel Order Management System")
    st.markdown("---")
    
    # Sidebar for navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox("Choose a page:", ["Home", "Data Preview"])
    
    if page == "Home":
        st.header("Generate Reports")
        
        # Date selector
        col1, col2 = st.columns([1, 2])
        with col1:
            selected_date = st.date_input(
                "Select Date:",
                value=datetime.now().date(),
                help="Select the date for which you want to generate reports"
            )
        
        # Generate reports button
        if st.button("🔄 Generate Reports", type="primary"):
            # Initialize progress tracking
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # Step 1: Fetch data
            status_text.text("Step 1/4: Fetching data from Google Sheets...")
            progress_bar.progress(25)
            
            df = get_google_sheets_data()
            
            if not df.empty:
                # Step 2: Process data
                status_text.text("Step 2/4: Processing data...")
                progress_bar.progress(50)
                
                # Step 3: Generate reports (synchronously)
                status_text.text("Step 3/4: Generating reports...")
                progress_bar.progress(75)
                
                try:
                    # Call the synchronous version instead of using threading
                    veg_report_data, vendor_report_data, combined_pdf_buffer, individual_hotel_pdf_buffer = generate_reports(df, selected_date)
                    
                    # Step 4: Complete
                    status_text.text("Step 4/4: Finalizing...")
                    progress_bar.progress(100)
                    
                    if veg_report_data is not None:
                        # Display summary
                        status_text.text("✅ Reports generated successfully!")
                        st.success(f"Data processed successfully for {selected_date}")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Total Vegetables", len(veg_report_data))
                        with col2:
                            st.metric("Total Vendors", len(vendor_report_data) if vendor_report_data else 0)
                        
                        # PDF download buttons
                        st.markdown("### 📥 Download Reports")
                        
                        # Create two columns for download buttons
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            if combined_pdf_buffer:
                                st.download_button(
                                    label="📊 Download Complete Summary Report",
                                    data=combined_pdf_buffer.getvalue(),
                                    file_name=f"complete_order_report_{selected_date.strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    help="Downloads vegetable-wise and vendor-wise summary reports in a single PDF"
                                )
                        
                        with col2:
                            if individual_hotel_pdf_buffer:
                                st.download_button(
                                    label="🏨 Download Individual Hotel Reports",
                                    data=individual_hotel_pdf_buffer.getvalue(),
                                    file_name=f"individual_hotel_reports_{selected_date.strftime('%Y%m%d')}.pdf",
                                    mime="application/pdf",
                                    help="Downloads individual reports for each hotel (one hotel per page)"
                                )
                        
                        # Preview data
                        with st.expander("🔍 Preview Vegetable Report Data (Sorted Alphabetically)"):
                            st.dataframe(veg_report_data, use_container_width=True)
                        
                        if vendor_report_data:
                            with st.expander("🔍 Preview Vendor Report Data (Sorted Alphabetically)"):
                                for vendor, data in vendor_report_data.items():
                                    st.subheader(f"Vendor: {vendor}")
                                    st.dataframe(data, use_container_width=True)
                    else:
                        st.warning("No data found for the selected date.")
                
                except Exception as e:
                    st.error(f"Error generating reports: {str(e)}")
                
                finally:
                    # Clean up progress indicators
                    progress_bar.empty()
                    status_text.empty()
            else:
                progress_bar.empty()
                status_text.empty()
                st.error("Failed to fetch data from Google Sheets.")
    
    elif page == "Data Preview":
        st.header("📋 Data Preview")
        
        with st.spinner("Loading data from Google Sheets..."):
            df = get_google_sheets_data()
        
        if not df.empty:
            st.success(f"Successfully loaded {len(df)} records")
            
            # Show basic info
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Records", len(df))
            with col2:
                st.metric("Unique Hotels", df['MAIN HOTEL NAME'].nunique() if 'MAIN HOTEL NAME' in df.columns else 0)
            with col3:
                st.metric("Unique Vegetables", df['PIVOT_VEGETABLE_NAME'].nunique() if 'PIVOT_VEGETABLE_NAME' in df.columns else 0)
            
            # Display data
            st.subheader("Raw Data")
            st.dataframe(df, use_container_width=True, height=400)
            
            # Show column info
            with st.expander("📊 Column Information"):
                st.write("**Columns in the dataset:**")
                for i, col in enumerate(df.columns, 1):
                    st.write(f"{i}. {col}")
        
        else:
            st.error("No data available or failed to connect to Google Sheets.")

if __name__ == "__main__":
    main()