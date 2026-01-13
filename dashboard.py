import streamlit as st
import pandas as pd
import io
import re

# Set page config
st.set_page_config(page_title="Tickets Tracking Dashboard", layout="wide")

st.title("📞 Tickets Tracking Dashboard")
st.markdown("Upload your **Incoming**, **Outgoing**, and **Tickets** CSV files to generate the agent performance report.")

# Sidebar for file uploads and settings
with st.sidebar:
    st.header("Upload Files")
    incoming_file = st.file_uploader("Upload Incoming Calls CSV", type=['csv'], key="inc")
    outgoing_file = st.file_uploader("Upload Outgoing Calls CSV", type=['csv'], key="out")
    tickets_file = st.file_uploader("Upload Tickets Dump CSV", type=['csv'], key="tick")
    
    st.divider()
    st.header("Settings")
    report_date = st.date_input("Report Date", value="today")

def clean_agent_name(name):
    if pd.isna(name):
        return 'Unassigned'
    name_str = str(name)
    # Remove "-Extension..." or " Extension..." or "(...)"
    cleaned = re.sub(r'\s*(?:-?Extension.*|\(.*\))', '', name_str, flags=re.IGNORECASE)
    
    # Specific Fixes
    # Remove "Toga" if present (case insensitive)
    cleaned = re.sub(r'\s*toga\s*', '', cleaned, flags=re.IGNORECASE)
    
    # Aggressively strip non-alphanumeric characters from ends (e.g. backticks)
    cleaned = re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', cleaned)
    
    cleaned = cleaned.strip()
    
    # Filter "No Agent" or strictly invalid names -> Assign to "Unassigned"
    if cleaned.lower() in ['no agent', 'n.a.', 'n/a', '---', '', 'nan', 'none']:
        return 'Unassigned'
        
    return cleaned.title() if cleaned else 'Unassigned'

@st.cache_data
def load_csv(uploaded_file):
    """
    Robust CSV loader that tries different encodings.
    """
    if uploaded_file is None:
        return None
    
    encodings = ['utf-8', 'latin1', 'cp1252', 'utf-16']
    for encoding in encodings:
        try:
            uploaded_file.seek(0)
            df = pd.read_csv(uploaded_file, encoding=encoding)
            # Clean column names
            df.columns = df.columns.str.strip()
            return df
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError:
            st.warning(f"File {uploaded_file.name} is empty.")
            return None
        except Exception as e:
            st.error(f"Error reading {uploaded_file.name}: {e}")
            return None
    
    st.error(f"Failed to read {uploaded_file.name} with standard encodings.")
    return None

@st.cache_data
def process_data(incoming_df, outgoing_df, tickets_df):
    
    collected_dates = set()
    
    # --- Helper: Calculate Metrics for a single Source ---
    def calculate_source_metrics(df, source_type):
        metrics = pd.DataFrame()
        
        # 0. Extract Date if possible
        # Incoming/Outgoing: 'Date' (e.g., "12-Jan 22:33:18")
        # Tickets: 'Created Time' (e.g., "15-12-2025 13:13")
        date_col = None
        if source_type in ['Incoming', 'Outgoing']:
            col_match = [c for c in df.columns if c.lower() == 'date']
            if col_match: date_col = col_match[0]
        elif source_type == 'Tickets':
            col_match = [c for c in df.columns if 'created time' in c.lower()]
            if col_match: date_col = col_match[0]
            
        if date_col:
            # Try parsing first few non-null
            sample_dates = df[date_col].dropna().head(50)
            for d in sample_dates:
                try:
                    # Heuristic: split by space to get date part
                    d_part = str(d).split(' ')[0]
                    collected_dates.add(d_part)
                except:
                    pass

        # 1. Identify Agent Column
        agent_col = None
        if source_type == 'Incoming':
            col_match = [c for c in df.columns if 'answered by agent' in c.lower()]
            if col_match: agent_col = col_match[0]
        elif source_type == 'Outgoing':
            col_match = [c for c in df.columns if 'agent name' in c.lower()]
            if col_match: agent_col = col_match[0]
        elif source_type == 'Tickets':
            # Looking for 'Agent' based on tickets.csv header
            col_match = [c for c in df.columns if c.lower() == 'agent']
            if col_match: agent_col = col_match[0]
            
        if not agent_col:
            st.warning(f"{source_type} data missing agent name column. Skipping metrics for {source_type}.")
            return None

        # 2. Clean Names
        df['CleanAgentName'] = df[agent_col].apply(clean_agent_name)
        # No need to drop - 'Unassigned' is returned for empty/invalid names
        
        if df.empty:
            return None

        # 3. Compute Metrics based on Source Type
        
        # --- PHONE METRICS (Incoming/Outgoing) ---
        if source_type in ['Incoming', 'Outgoing']:
            # Call Count
            counts = df.groupby('CleanAgentName').size()
            metrics = metrics.join(counts.rename(f'{source_type} Calls'), how='outer')
            
            # Answered Count
            status_col = next((c for c in df.columns if c.lower() == 'status'), None)
            if status_col:
                answered_mask = df[status_col].str.lower().fillna('') == 'answered'
                answered_counts = df[answered_mask].groupby('CleanAgentName').size()
                metrics = metrics.join(answered_counts.rename(f'{source_type} Answered'), how='outer')
        
        # --- TICKET METRICS ---
        elif source_type == 'Tickets':
            # Status based metrics
            status_col = next((c for c in df.columns if c.lower() == 'status'), None)
            
            if status_col:
                # Tickets Resolved
                # Check for "Resolved" string
                resolved_mask = df[status_col].str.lower().fillna('') == 'resolved'
                resolved_counts = df[resolved_mask].groupby('CleanAgentName').size()
                metrics = metrics.join(resolved_counts.rename('Tickets Resolved'), how='outer')
                
                # Tickets Closed
                # Check for "Closed" string
                closed_mask = df[status_col].str.lower().fillna('') == 'closed'
                closed_counts = df[closed_mask].groupby('CleanAgentName').size()
                metrics = metrics.join(closed_counts.rename('Tickets Closed'), how='outer')
            else:
                 st.warning("Tickets CSV missing 'Status' column.")

        return metrics

    # --- Process All Files ---
    final_df = pd.DataFrame()
    
    # 1. Incoming
    if incoming_df is not None:
        m = calculate_source_metrics(incoming_df, 'Incoming')
        if m is not None: final_df = final_df.join(m, how='outer')
        
    # 2. Outgoing
    if outgoing_df is not None:
        m = calculate_source_metrics(outgoing_df, 'Outgoing')
        if m is not None: final_df = final_df.join(m, how='outer')
        
    # 3. Tickets
    if tickets_df is not None:
        m = calculate_source_metrics(tickets_df, 'Tickets')
        if m is not None: final_df = final_df.join(m, how='outer')
        
    if final_df.empty:
        return pd.DataFrame(), None

    # Fill NA
    final_df = final_df.fillna(0)
    
    # --- Aggregate Totals ---
    
    inc_calls = final_df['Incoming Calls'] if 'Incoming Calls' in final_df.columns else 0
    out_calls = final_df['Outgoing Calls'] if 'Outgoing Calls' in final_df.columns else 0
    final_df['Total Calls'] = inc_calls + out_calls
    
    inc_ans = final_df['Incoming Answered'] if 'Incoming Answered' in final_df.columns else 0
    out_ans = final_df['Outgoing Answered'] if 'Outgoing Answered' in final_df.columns else 0
    final_df['Total Answered'] = inc_ans + out_ans
    
    # Ticket Totals
    tick_res = final_df['Tickets Resolved'] if 'Tickets Resolved' in final_df.columns else 0
    tick_clo = final_df['Tickets Closed'] if 'Tickets Closed' in final_df.columns else 0
    final_df['Total Tickets Activity'] = tick_res + tick_clo
    
    final_df = final_df.fillna(0).astype(int)
    final_df.index.name = 'Agent Name'

    # --- Add Cumulative Row ---
    # Sum numeric columns
    totals = final_df.sum()
    totals.name = 'Total'
    final_df = final_df._append(totals)
    
    # Sort dates to find range
    date_str = None
    if collected_dates:
        sorted_dates = sorted(list(collected_dates))
        if len(sorted_dates) == 1:
            date_str = sorted_dates[0]
        else:
            date_str = f"{sorted_dates[0]} to {sorted_dates[-1]}"
    
    return final_df, date_str

# Main Logic
if incoming_file is None and outgoing_file is None and tickets_file is None:
    st.info("Please upload at least one CSV file to begin.")
else:
    # Load files
    inc_df = load_csv(incoming_file)
    out_df = load_csv(outgoing_file)
    tick_df = load_csv(tickets_file)
    
    try:
        results, doc_date = process_data(inc_df, out_df, tick_df)
        
        # Display Date (user-selected)
        st.caption(f"📅 **Data Date: {report_date.strftime('%d-%b-%Y')}**")
        
        if results is not None and not results.empty:
            # Summary Metrics - Use the 'Total' row directly to avoid double-counting
            st.divider()
            cols = st.columns(4)
            
            # Exclude the 'Total' row for agent count
            agent_count = len(results) - 1  # Subtract 1 for the Total row
            cols[0].metric("Total Agents", agent_count)
            
            # Get values from the 'Total' row (last row)
            total_row = results.loc['Total'] if 'Total' in results.index else None
            
            if total_row is not None:
                if 'Total Answered' in results.columns:
                    cols[1].metric("Total Calls Answered", int(total_row['Total Answered']))
                if 'Total Tickets Activity' in results.columns:
                    cols[2].metric("Total Tickets Activity", int(total_row['Total Tickets Activity']))
                if 'Total Calls' in results.columns:
                    cols[3].metric("Total Calls", int(total_row['Total Calls']))
            
            st.divider()
            st.subheader("Agent Performance Details")
            
            # Column Selection
            all_cols = results.columns.tolist()
            
            # Defaults
            default_cols = ['Incoming Answered', 'Outgoing Answered', 'Total Answered', 'Tickets Resolved', 'Tickets Closed', 'Total Tickets Activity']
            
            # Valid defaults check
            valid_defaults = [c for c in default_cols if c in all_cols]
            if not valid_defaults: valid_defaults = all_cols
            
            selected_cols = st.multiselect("Select Columns to Display", all_cols, default=valid_defaults)
            
            if selected_cols:
                display_df = results[selected_cols]
                st.dataframe(display_df, use_container_width=True)
                
                csv = display_df.to_csv()
                st.download_button("Download Report (CSV)", csv, "agent_report.csv", "text/csv")
            else:
                st.warning("Please select at least one column to display.")
            
            # Debug View
            with st.expander("Debug: Inspect Raw vs Cleaned Names"):
                st.write("Check how agent names are extracted from each file.")
                
                if inc_df is not None:
                    st.write("**Incoming File**")
                    col = [c for c in inc_df.columns if 'answered by agent' in c.lower()]
                    if col: st.dataframe(inc_df[[col[0]]].drop_duplicates().assign(Cleaned=lambda x: x[col[0]].apply(clean_agent_name)))

                if out_df is not None:
                    st.write("**Outgoing File**")
                    col = [c for c in out_df.columns if 'agent name' in c.lower()]
                    if col: st.dataframe(out_df[[col[0]]].drop_duplicates().assign(Cleaned=lambda x: x[col[0]].apply(clean_agent_name)))

                if tick_df is not None:
                    st.write("**Tickets File**")
                    col = [c for c in tick_df.columns if c.lower() == 'agent']
                    if col: st.dataframe(tick_df[[col[0]]].drop_duplicates().assign(Cleaned=lambda x: x[col[0]].apply(clean_agent_name)))

        else:
            st.warning("No valid data found after processing. Check your column names or data content.")
            
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        st.write("Please check the console for details.")
