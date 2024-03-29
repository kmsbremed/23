"""Methods to assist in the conversion of single source Excel to JSON."""
import collections
import json
import re
import itertools

import numpy as np
import pandas as pd

DX_CODE_CATEGORY = ['DX_CODE']
DX_CODE_X_CATEGORY = ['DX_CODE_X', 'DX_CODE_Exe', 'DX_CODE_Exl']
ENC_PROC_CODE_CATEGORY = ['ENCOUNTER_CODE', 'PROC_CODE']
QUALITY_CODE_CATEGORY = ['PD_Exe', 'PD_Exl', 'PN_X', 'PN']
ADDITIONAL_ENC_PROC_CODE_CATEGORY = ['ADDITIONAL_PROCEDURE_CODE']

# Descriptions of these options can be found at
# https://cmsgov.github.io/qpp-submissions-docs/measurements#single-performance-rate-measurements
PERFORMANCE_OPTIONS = {
    'PN_X': 'performanceNotMet',
    'PN': 'performanceMet',
    'PD_Exe': 'eligiblePopulationException',
    'PD_Exl': 'eligiblePopulationExclusion'
}


def determine_element_category(element):
    """Determine the category that the data_element belongs to."""
    # FIXME: Allow for case-insensitive treatment of these strings.
    for category in (QUALITY_CODE_CATEGORY):
        if len(re.findall(".*{}_*\d*".format(category), element)) != 0:
            return category

    # Use starts_with to cover the case of additional diagnosis codes, which end in _B.
    # This also covers measures with multiple eligibility options (e.g., ENCOUNTER_CODE_1).
    for category in (ENC_PROC_CODE_CATEGORY + DX_CODE_X_CATEGORY + DX_CODE_CATEGORY):
        if element.startswith(category):
            return category

    # Additional procedure codes (used in measure 155 and 226).
    if element.endswith('DENOM_CODE'):
        return 'ADDITIONAL_PROCEDURE_CODE'

    # Drop duplicate PD elements, since these are capture in PN, PN_X, etc.
    if len(re.findall(".*_PD_?\d?$", element)) != 0:
        return 'DROP'

    # If the data element is not something we know how to handle, raise an error.
    else:
        print('{} data element not recognized!'.format(element))
        raise(NotImplementedError)


def find_min_max_age(age_string):
    """
    Given an age string, parse it and produce minimum and maximum age for the measure.

    If the maximum age is null, returns None as the upper bound.
    """
    month_regex = re.compile('^≥(\d+)\s?mo$')
    if re.match(month_regex, age_string):
        min_age = float(re.match(month_regex, age_string).groups()[0]) / 12
        max_age = None
    else:
        try:
            min_age, max_age = re.findall('\d+', age_string)
        except ValueError:
            min_age, max_age = re.findall('\d+', age_string)[0], None
    return pd.Series([min_age, max_age], index=['min_age', 'max_age'], dtype=float)


def get_gender(gender_string):
    """Given the gender string, returns sex_code of 'M', 'F', or None."""
    sex_code = gender_string if gender_string in ('M', 'F') else None
    return pd.Series([sex_code], index=['sex_code'])


def is_additional_diagnosis_code(data_element_name):
    """
    Determine if a diagnosis code is an "additional diagnosis code".

    Codes are additional diagnosis codes if they contain _B in their data element name.
    """
    if not data_element_name:
        return False

    for category in DX_CODE_CATEGORY:
        if data_element_name.startswith(category):
            return '_B' in data_element_name
    else:
        return False


def convert_inclusion_exclusion_string_to_lists(input_string):
    """
    Convert a list of modifier and/or modifier exclusions to list.

    Args:
        input_string (str): String to be split into inclusions, exclusions.
    Returns:
        Inclusions and exclusions in the format [[inclusions], [exclusions]]
    """
    list_split_regex = re.compile(',\s*|\s*or\s*|≠\s*|=\s*')
    not_equals_split_regex = re.compile('≠\s*')

    included_excluded_string = re.split(not_equals_split_regex, input_string)

    if len(included_excluded_string) > 1:
        included_string = included_excluded_string[0] or ''
        excluded_string = included_excluded_string[1]
    else:
        included_string = included_excluded_string[0]
        excluded_string = ''

    included = [x for x in re.split(list_split_regex, included_string) if x]
    excluded = [x for x in re.split(list_split_regex, excluded_string) if x]

    return pd.Series([included, excluded])


def procedure_codes_to_dict(row):
    """
    Convert encounter and procedure codes to their necessary dictionary.

    This function is used to build eligibility options from a measure DataFrame.
    Given a row of data, return a dictionary of the form:
        {
            'code': code,
            'modifiers': [],
            'modifierExclusions': [],
            'placesOfService': [],
            'placesOfServiceExclusions': []
        },
    where modifiers and place of service are only present if they contain valid values.
    """
    if row['element_category'] not in (ENC_PROC_CODE_CATEGORY + ADDITIONAL_ENC_PROC_CODE_CATEGORY):
        return {}

    procedure_dict = {
        'code': row['code']
    }

    attribute_names = [
        'modifiers', 'modifierExclusions', 'placesOfService', 'placesOfServiceExclusions'
    ]

    for name in attribute_names:
        if row[name]:
            procedure_dict[name] = row[name]

    return procedure_dict


def quality_codes_to_dict(row):
    """
    Convert quality codes to dictionary.

    This function is used to build performance options from a measure DataFrame.
    Given a row of data, return a dictionary of the form:
        {
            'optionType': 'performanceMet',
            'qualityCodes: [{'code': code, 'modifiers': [], ...}, {'code': code}, ...]
            'codeset_number': 1
        }.
    Here codeset_number is optional: it is used to merge codes together then is deleted.
    """
    if row['element_category'] not in PERFORMANCE_OPTIONS:
        return {}

    performance_dict = {}
    performance_dict['optionType'] = PERFORMANCE_OPTIONS[row['element_category']]

    if not pd.isnull(row['codeset_number']):
        performance_dict['codeset_number'] = row['codeset_number']

    quality_dict = {
        'code': row['code']
    }
    attribute_names = [
        'modifiers', 'modifierExclusions', 'placesOfService', 'placesOfServiceExclusions'
    ]
    for name in attribute_names:
        if row[name]:
            quality_dict[name] = row[name]

    performance_dict['qualityCodes'] = [quality_dict]
    return performance_dict


def merge_multiple_performance_options(performance_options):
    """Merge performance options that have the same codeset_number."""
    updated_performance_options = []
    multiple_code_sets = collections.defaultdict(list)  # list of tuples (set, [options])

    # Key by codeset_number.
    for option in performance_options:
        codeset_number = option.pop('codeset_number')
        if codeset_number > 0:
            multiple_code_sets[codeset_number].append(option)
        else:
            updated_performance_options.append(option)  # Not a multiple code set

    # Merge quality codes for ones with the same codeset_number.
    # Only relevant when there are multiple code sets.
    for number, set_list in multiple_code_sets.items():

        keyed_options = ((x["optionType"], x["qualityCodes"]) for x in set_list)
        sorted_keyed_options = sorted(keyed_options, key=lambda x: x[0])
        new_opts = [
            {"optionType": opt_type,
             "qualityCodes": [c for _, codes in opts for c in codes]}
            for opt_type, opts in itertools.groupby(sorted_keyed_options, lambda x: x[0])
        ]
        updated_performance_options.extend(new_opts)

    return updated_performance_options


def merge_multiple_eligibility_options(single_source_dict):
    """Merge together measures with multiple options denominated by .00 vs .01, etc."""

    merged_single_source = {}

    for measure in single_source_dict:

        if measure.count(".") == 0:
            option_group = "00"
        else:
            option_group = measure.split(".")[1]

        curMeas = single_source_dict[measure]
        for eo in curMeas['eligibilityOptions']:
            eo["optionGroup"] = option_group
        for po in curMeas["performanceOptions"]:
            po["optionGroup"] = option_group

        merged_measure_id = measure.split(".")[0]
        merged_data = merged_single_source.get(merged_measure_id, {})
        merged_data["eligibilityOptions"] = merged_data.get("eligibilityOptions", []) + \
                                            curMeas["eligibilityOptions"]
        merged_data["performanceOptions"] = merged_data.get("performanceOptions", []) + \
                                            curMeas["performanceOptions"]
        merged_single_source[merged_measure_id] = merged_data

    return merged_single_source


def add_row_level_information_to_dataframe(single_source_df):
    """
    Add row-level information to the single source DataFrame.

    Occurs in-place.

    This will add the following fields:
        'element_category': procedure code, quality code, etc.
        'min_age', 'max_age': in years
        'sex_code': 'M' or 'F' or None
        'modifiers', 'modifierExclusions'
        'placesOfService', 'placesOfServiceExclusions'
        'is_additional_diagnosis_code'
        'codeset_number': for measures with multiple code sets
    """
    pd.set_option('mode.chained_assignment', None)
    single_source_df['element_category'] = single_source_df['data_element_name'].apply(
        determine_element_category
    )
    single_source_df = single_source_df[single_source_df['element_category'] != 'DROP']
    # Create min_age and max_age floats from string age column.
    single_source_df[['min_age', 'max_age']] = single_source_df['age'].apply(
        find_min_max_age).astype(float)
    # Assign values for gender restrictions.
    single_source_df[['sex_code']] = single_source_df['gender'].apply(get_gender)

    # Process the modifiers into two lists: modifiers to include, modifiers to exclude.
    single_source_df.modifier.fillna('', inplace=True)
    single_source_df['modifiers'], single_source_df['modifierExclusions'] = \
        zip(*single_source_df['modifier'].map(convert_inclusion_exclusion_string_to_lists))

    # Process places of service (POS) into two lists: POS to include, POS to exclude.
    single_source_df.place_of_service.fillna('', inplace=True)
    single_source_df['placesOfService'], single_source_df['placesOfServiceExclusions'] = \
        zip(*single_source_df['place_of_service'].map(convert_inclusion_exclusion_string_to_lists))

    # Assign additional diagnosis codes if present.
    single_source_df['is_additional_diagnosis_code'] = single_source_df['data_element_name'].apply(
        is_additional_diagnosis_code)

    # Extract multiple code sets number from data_element name.
    # Parts of a multiple code set grouping will have codeset number equal to that grouping number,
    # e.g. '_2' --> 2. Rows that are not part of a multiple code set will have codeset_number -1.
    single_source_df['codeset_number'] = \
        single_source_df['data_element_name'].str.extract(r'_([0-9]+)_', expand=False)
    single_source_df['codeset_number'].fillna(-1, inplace=True)
    single_source_df['codeset_number'] = single_source_df['codeset_number'].astype(int)
    
    pd.set_option('mode.chained_assignment', 'warn')
    return single_source_df


def extract_performance_options_from_measure_dataframe(measure_df):
    """Extract a list of performance options from the subframe corresponding to a single measure."""
    performance_df = measure_df[measure_df['element_category'].isin(QUALITY_CODE_CATEGORY)]
    return performance_df.apply(lambda row: quality_codes_to_dict(row), axis=1).tolist()


def extract_eligibility_options_from_measure_dataframe(measure_df):
    """Extract a list of eligibility options from the subframe corresponding to a single measure."""
    # Choose a representative row to determine age and sex requirements.
    representative_row = measure_df[measure_df['element_category'] == 'PN'].iloc[0]
    # Exclude rows corresponding to quality codes as they do not affect eligibility options.
    eligibility_df = measure_df[
        ~measure_df['element_category'].isin(QUALITY_CODE_CATEGORY + [None])
    ]

    eligibility_options = []
    # Each distinct codeset creates a new eligibility option.

    # This bit of code is to handle when common eligibility options are not explicitly part of a group
    codeset_numbers = eligibility_df["codeset_number"].unique()
    if -1 in codeset_numbers and 1 in codeset_numbers:
        un_numbered = eligibility_df[eligibility_df["codeset_number"] == -1]
        new_elig_out = eligibility_df[eligibility_df["codeset_number"] != -1]
        for c in (set(codeset_numbers) - {-1}):
            new_numbered = un_numbered.copy()
            new_numbered["codeset_number"] = c
            new_elig_out = new_elig_out.append(new_numbered)
        eligibility_df = new_elig_out

    for codeset_number, codeset_df in eligibility_df.groupby('codeset_number'):
        procedure_codes = list(codeset_df[
            codeset_df['element_category'].isin(ENC_PROC_CODE_CATEGORY)
        ].apply(
            lambda row: procedure_codes_to_dict(row), axis=1, result_type = 'reduce'
        ))

        additional_procedure_codes = list(codeset_df[
            codeset_df['element_category'].isin(ADDITIONAL_ENC_PROC_CODE_CATEGORY)
        ].apply(
            lambda row: procedure_codes_to_dict(row), axis=1, result_type = 'reduce'
        ))

        dx_codes_df = codeset_df[codeset_df['element_category'].isin(DX_CODE_CATEGORY)]

        diagnosis_codes = list(
            dx_codes_df[~dx_codes_df['is_additional_diagnosis_code']]['code']
        )
        additional_diagnosis_codes = list(
            dx_codes_df[dx_codes_df['is_additional_diagnosis_code']]['code']
        )
        diagnosis_exclusion_codes = list(
            codeset_df[codeset_df['element_category'].isin(DX_CODE_X_CATEGORY)]['code']
        )

        # Build the entire eligibility option with all keys, even if they have null values.
        eligibility_option = {
            'procedureCodes': procedure_codes,
            'additionalProcedureCodes': additional_procedure_codes,
            'diagnosisCodes': diagnosis_codes,
            'diagnosisExclusionCodes': diagnosis_exclusion_codes,
            'additionalDiagnosisCodes': additional_diagnosis_codes,
            'sexCode': representative_row['sex_code'],
            'minAge': representative_row['min_age'],
            'maxAge': representative_row['max_age'],
        }

        # Remove null or invalid values from the eligibility option.
        # Build a list of keys to remove to avoid 'dictionary changed size during iteration' error.
        keys_to_remove = []
        for k, v in eligibility_option.items():
            if v is None:
                keys_to_remove.append(k)
            elif isinstance(v, list) and len(v) == 0:
                keys_to_remove.append(k)
            elif isinstance(v, float) and np.isnan(v):
                keys_to_remove.append(k)

        for k in keys_to_remove:
            eligibility_option.pop(k)

        eligibility_options.append(eligibility_option)
    
    return eligibility_options
