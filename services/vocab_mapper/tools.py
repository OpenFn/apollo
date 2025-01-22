def process_inputs(input_data, mapper):
    """Process inputs to map with a VocabMapper one by one."""
    results = []
    for row in input_data:
        result = mapper.map_term(
            input_term=row['input_term'],
            general_info=row.get('general_info', ''),
            specific_info=row.get('specific_info', '')
        )
        results.append({
            'input': row,
            'mapping': result
        })
    return results