import streamlit as st
import pandas as pd
import io
import re

# Set page config
st.set_page_config(page_title="Tickets Tracking Dashboard", layout="wide")

st.title("📞 Tickets Tracking Dashboard")
st.markdown("Upload your **Incoming** and **Outgoing** call CSV files to generate the agent performance report.")

# Sidebar for file uploads
with st.sidebar:
    st.header("Upload Files")
    incoming_file = st.file_uploader("Upload Incoming Calls CSV", type=['csv'])
    outgoing_file = st.file_uploader("Upload Outgoing Calls CSV", type=['csv'])

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
def process_data(incoming_df, outgoing_df):
    
    results_list = []
    
    # helper for metrics
    def calculate_metrics(df, source_type):
        metrics = pd.DataFrame()
        
        # Identify Agent Name Column
        agent_col = None
        if source_type == 'Incoming':
            # Check for "Answered By Agent"
            col_match = [c for c in df.columns if 'answered by agent' in c.lower()]
            if col_match:
                agent_col = col_match[0]
        else: # Outgoing
            # Check for "Agent Name..."
            col_match = [c for c in df.columns if 'agent name' in c.lower()]
            if col_match:
                agent_col = col_match[0]
                
        if not agent_col:
            st.warning(f"{source_type} data missing agent name column. Skipping agent metrics for {source_type}.")
            return None

        # Clean Names
        df['CleanAgentName'] = df[agent_col].apply(clean_agent_name)
        # Filter invalid
        df = df[~df['CleanAgentName'].isin(['---', '', 'Nan', 'None', None])]
        
        if df.empty:
            return None

        # 1. Counts
        counts = df.groupby('CleanAgentName').size()
        metrics = metrics.join(counts.rename(f'{source_type} Calls'), how='outer')
        
        # 2. Resolved (Status = Answered)
        status_col = next((c for c in df.columns if c.lower() == 'status'), None)
        if status_col:
            resolved_mask = df[status_col].str.lower().fillna('') == 'answered'
            resolved_counts = df[resolved_mask].groupby('CleanAgentName').size()
            metrics = metrics.join(resolved_counts.rename(f'{source_type} Resolved'), how='outer')
        
        # 3. Closed (Hangup = Normal clearing)
        hangup_col = next((c for c in df.columns if 'hangup' in c.lower() and 'cause' in c.lower()), None)
        if hangup_col:
            closed_mask = df[hangup_col].str.lower().fillna('') == 'normal clearing'
            closed_counts = df[closed_mask].groupby('CleanAgentName').size()
            metrics = metrics.join(closed_counts.rename(f'{source_type} Closed'), how='outer')
            
        return metrics

    # Process Incoming
    incoming_metrics = pd.DataFrame()
    if incoming_df is not None:
        incoming_metrics = calculate_metrics(incoming_df, 'Incoming')
        
    # Process Outgoing
    outgoing_metrics = pd.DataFrame()
    if outgoing_df is not None:
        outgoing_metrics = calculate_metrics(outgoing_df, 'Outgoing')
        
    # Merge
    # If both None, return None
    if incoming_metrics is None and outgoing_metrics is None:
        return None
        
    final_df = pd.DataFrame()
    
    if incoming_metrics is not None:
        final_df = final_df.join(incoming_metrics, how='outer')
        
    if outgoing_metrics is not None:
        final_df = final_df.join(outgoing_metrics, how='outer')
        
    if final_df.empty:
        return pd.DataFrame() # Return empty but valid DF
    
    # Fill NA
    final_df = final_df.fillna(0)
    
    # Aggregate Totals
    # Robust summing: check if columns exist before summing
    
    # Total Calls
    inc_calls = final_df['Incoming Calls'] if 'Incoming Calls' in final_df.columns else 0
    out_calls = final_df['Outgoing Calls'] if 'Outgoing Calls' in final_df.columns else 0
    final_df['Total Calls'] = inc_calls + out_calls
    
    # Total Resolved
    inc_res = final_df['Incoming Resolved'] if 'Incoming Resolved' in final_df.columns else 0
    out_res = final_df['Outgoing Resolved'] if 'Outgoing Resolved' in final_df.columns else 0
    final_df['Resolved'] = inc_res + out_res
    
    # Total Closed
    inc_closed = final_df['Incoming Closed'] if 'Incoming Closed' in final_df.columns else 0
    out_closed = final_df['Outgoing Closed'] if 'Outgoing Closed' in final_df.columns else 0
    final_df['Tickets Closed'] = inc_closed + out_closed
    
    # Keep main columns for display
    display_cols = ['Incoming Calls', 'Outgoing Calls', 'Resolved', 'Tickets Closed']
    # Filter only those that exist (or add them as 0 if missing for consistency?)
    # Let's add them as 0 if missing so the table structure is consistent
    for col in display_cols:
        if col not in final_df.columns:
            final_df[col] = 0
            
    final_df = final_df[display_cols]
    final_df = final_df.astype(int)
    final_df.index.name = 'Agent Name'
    
    return final_df

# Main Logic
if incoming_file is None and outgoing_file is None:
    st.info("Please upload at least one CSV file to begin.")
else:
    # Load files
    inc_df = load_csv(incoming_file)
    out_df = load_csv(outgoing_file)
    
    if inc_df is not None or out_df is not None:
        try:
            results = process_data(inc_df, out_df)
            
            if results is not None and not results.empty:
                # Summary
                st.divider()
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Agents", len(results))
                c2.metric("Total Resolved", results['Resolved'].sum())
                c3.metric("Total Closed", results['Tickets Closed'].sum())
                c4.metric("Total Calls", (results['Incoming Calls'].sum() + results['Outgoing Calls'].sum()))
                
                st.divider()
                st.subheader("Agent Performance Details")
                st.dataframe(results, use_container_width=True)
                
                csv = results.to_csv()
                st.download_button("Download Report (CSV)", csv, "agent_report.csv", "text/csv")
                
                # Debug View
                with st.expander("Debug: Inspect Raw vs Cleaned Names"):
                    st.write("This section shows how agent names were extracted from the files.")
                    
                    if inc_df is not None:
                        st.subheader("Incoming File")
                        # Recalculate for display
                        col_match = [c for c in inc_df.columns if 'answered by agent' in c.lower()]
                        if col_match:
                            debug_inc = inc_df[[col_match[0]]].drop_duplicates()
                            debug_inc['Cleaned By App'] = debug_inc[col_match[0]].apply(clean_agent_name)
                            st.dataframe(debug_inc)
                            
                    if out_df is not None:
                        st.subheader("Outgoing File")
                        col_match = [c for c in out_df.columns if 'agent name' in c.lower()]
                        if col_match:
                            debug_out = out_df[[col_match[0]]].drop_duplicates()
                            debug_out['Cleaned By App'] = debug_out[col_match[0]].apply(clean_agent_name)
                            st.dataframe(debug_out)

            else:
                st.warning("No valid data found after processing. Check your column names or data content.")
        except Exception as e:
            st.error(f"Unexpected error: {e}")
            st.write("Please check the console or try different files.")
