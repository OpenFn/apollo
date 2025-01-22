def format_google_sheets_input(data):
    """Format Google Sheets input data to process with process_inputs."""
    values = data['data']['values']
    headers = values[0]
    input_data = []

    # Get column indices (both required and optional)
    try:
        input_field_idx = headers.index('input_field')
    except ValueError as e:
        raise ValueError(f"Required column 'input_field' not found in headers: {e}")

    # Get indices for all possible columns, None if not present
    column_indices = {
        'input_field': input_field_idx,
        'source_dataset_information': headers.index('source_dataset_information') if 'source_dataset_information' in headers else None,
        'input_term_information': headers.index('input_term_information') if 'input_term_information' in headers else None,
        'ai_shortlist': headers.index('ai_shortlist') if 'ai_shortlist' in headers else None,
        'ai_selection': headers.index('ai_selection') if 'ai_selection' in headers else None,
        'final_selected_answer': headers.index('final_selected_answer') if 'final_selected_answer' in headers else None
    }

    # Process input rows
    for row in values[1:]:  # Skip header
        if not row:
            continue
            
        entry = {
            'input_term': row[input_field_idx],
            'general_info': row[column_indices['source_dataset_information']] if (column_indices['source_dataset_information'] is not None and len(row) > column_indices['source_dataset_information']) else '',
            'specific_info': row[column_indices['input_term_information']] if (column_indices['input_term_information'] is not None and len(row) > column_indices['input_term_information']) else ''
        }
        input_data.append(entry)
    
    return input_data, column_indices, values  # Return indices and original values for output formatting

def format_google_sheets_output(data, mapping_results, column_indices, original_values):
    """Format the output of process_inputs for Google Sheets."""
    output_headers = [
        "input_field",
        "source_dataset_information",
        "input_term_information",
        "ai_shortlist",
        "ai_selection",
        "final_selected_answer"
    ]
    
    output_values = [output_headers]  # Start with headers
    
    # For each row in the original input
    for i, row in enumerate(original_values[1:], 1):  # Skip header, keep original indexing
        if not row:  # Preserve empty rows
            output_values.append([])
            continue
            
        # Get the mapping result for this row
        mapping_result = mapping_results[i-1]['mapping'] if i-1 < len(mapping_results) else {}
        
        # Create new row with preserved original values and new mapping results
        new_row = [
            row[column_indices['input_field']] if len(row) > column_indices['input_field'] else '',  # input_field
            row[column_indices['source_dataset_information']] if (column_indices['source_dataset_information'] is not None and len(row) > column_indices['source_dataset_information']) else '',  # source_dataset_information
            row[column_indices['input_term_information']] if (column_indices['input_term_information'] is not None and len(row) > column_indices['input_term_information']) else '',  # input_term_information
            mapping_result.get('shortlist', ''),  # ai_shortlist
            mapping_result.get('final_selection', ''),  # ai_selection (from final_selection)
            row[column_indices['final_selected_answer']] if (column_indices['final_selected_answer'] is not None and len(row) > column_indices['final_selected_answer']) else ''  # preserved final_selected_answer
        ]
        
        output_values.append(new_row)

    return {
        "data": {
            "majorDimension": data['data']['majorDimension'],
            "range": data['data']['range'],
            "values": output_values
        },
        "references": data['references']
    }