import streamlit as st
import pandas as pd
import io
import re

# Set page config
st.set_page_config(page_title="Tickets Tracking Dashboard", layout="wide")

st.title("📞 Tickets Tracking Dashboard")
st.markdown("Upload your **Incoming**, **Outgoing**, and **Tickets** CSV files to generate the agent performance report.")

# Sidebar for file uploads
with st.sidebar:
    st.header("Upload Files")
    incoming_file = st.file_uploader("Upload Incoming Calls CSV", type=['csv'], key="inc")
    outgoing_file = st.file_uploader("Upload Outgoing Calls CSV", type=['csv'], key="out")
    tickets_file = st.file_uploader("Upload Tickets Dump CSV", type=['csv'], key="tick")

def clean_agent_name(name):
    if pd.isna(name):
        return None
    name_str = str(name)
    # Remove "-Extension..." or " Extension..." or "(...)"
    cleaned = re.sub(r'\s*(?:-?Extension.*|\(.*\))', '', name_str, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    # Normalize case
    return cleaned.title() if cleaned else None

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
    
    # --- Helper: Calculate Metrics for a single Source ---
    def calculate_source_metrics(df, source_type):
        metrics = pd.DataFrame()
        
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
        # Filter invalid
        df = df[~df['CleanAgentName'].isin(['---', '', 'Nan', 'None', None])]
        
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
        return pd.DataFrame()

    # Fill NA
    final_df = final_df.fillna(0)
    
    # --- Aggregate Totals ---
    
    # Total Calls = Incoming Answered? No, usually Calls = Total Attempts, match previous logic?
    # User asked for "Incoming Answered, Outgoing Answered, Total [Answered]". 
    # Let's keep Total Calls (Attempts) and Total Answered.
    
    inc_calls = final_df['Incoming Calls'] if 'Incoming Calls' in final_df.columns else 0
    out_calls = final_df['Outgoing Calls'] if 'Outgoing Calls' in final_df.columns else 0
    final_df['Total Calls'] = inc_calls + out_calls
    
    inc_ans = final_df['Incoming Answered'] if 'Incoming Answered' in final_df.columns else 0
    out_ans = final_df['Outgoing Answered'] if 'Outgoing Answered' in final_df.columns else 0
    final_df['Total Answered'] = inc_ans + out_ans
    
    # Tickets Total? Maybe not needed unless asked.
    
    final_df = final_df.fillna(0).astype(int)
    final_df.index.name = 'Agent Name'
    
    return final_df

# Main Logic
if incoming_file is None and outgoing_file is None and tickets_file is None:
    st.info("Please upload at least one CSV file to begin.")
else:
    # Load files
    inc_df = load_csv(incoming_file)
    out_df = load_csv(outgoing_file)
    tick_df = load_csv(tickets_file)
    
    try:
        results = process_data(inc_df, out_df, tick_df)
        
        if results is not None and not results.empty:
            # Summary Metrics - Adjusted based on what's available
            st.divider()
            cols = st.columns(4)
            cols[0].metric("Total Agents", len(results))
            
            if 'Total Answered' in results.columns:
                cols[1].metric("Total Calls Answered", results['Total Answered'].sum())
            if 'Tickets Resolved' in results.columns:
                cols[2].metric("Tickets Resolved", results['Tickets Resolved'].sum())
            if 'Tickets Closed' in results.columns:
                cols[3].metric("Tickets Closed", results['Tickets Closed'].sum())
            
            st.divider()
            st.subheader("Agent Performance Details")
            
            # Column Selection
            all_cols = results.columns.tolist()
            
            # Defaults based on latest user request + new ticket info
            # "Incoming Answered, Outgoing Answered, Total [Answered]"
            # Plus Tickets info is likely useful now that they uploaded it.
            default_cols = ['Incoming Answered', 'Outgoing Answered', 'Total Answered', 'Tickets Resolved', 'Tickets Closed']
            
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
