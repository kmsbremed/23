import pandas as pd
import os
import argparse


def printDf(df, f):
    columnOrder = ['VERSION', 'Measure_ID',
                   'DATA_ELEMENT_NAME',
                   'CODING_SYSTEM',
                   'CODE',
                   'MODIFIER',
                   'PLACE_OF_SERVICE',
                   'AGE',
                   'GENDER'
                   ]
    # to markdown is better but unfortunately not supported by current docker
    # however this can be used if running locally ( Requirement Python 3.8 )
    print(df[columnOrder].to_markdown(tablefmt="grid", index=False), file=f)
    # print(df[columnOrder].to_string(index=False), file=f)


def paragraph(f):
    print("", file=f)
    print("", file=f)


def getJoinMeta(row):
    val = "NONE"
    if (row["VERSION_new"] == "NEW") & (row["VERSION_base"] == "BASE"):
        val = "COMMON"
    elif row["VERSION_new"] == "NEW":
        val = "NEW"
    else:
        val = "BASE"
    return val


def columnToSet(df, column: str):
    return set(df[column].unique().tolist())


def analyze_difference(joint, partcolumn, partid, subcol, debug=False):
    subset = joint[joint[partcolumn] == partid]
    basedf = subset[(subset.VERSION == "BASE") | (subset.VERSION == "COMMON")]
    newdf = subset[(subset.VERSION == "NEW") | (subset.VERSION == "COMMON")]

    newids = columnToSet(newdf, subcol)
    baseids = columnToSet(basedf, subcol)

    added = newids - baseids
    removed = baseids - newids

    # get all the changed IDs
    changedids = columnToSet(subset[subset.VERSION != "COMMON"], subcol)

    changed = changedids - added - removed

    if debug == True:
        print("Added")
        print(added)
        print("Removed")
        print(removed)
        print("Changed")
        print(changed)

    return (subset, added | removed | changed, added, removed, changed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Parse arguments')
    parser.add_argument('--base', type=str, help='Base file with path ',default="data/2020_Claims_SingleSource_v1.4.csv")
    parser.add_argument('--new', type=str, help='New file with path ',default="data/2021_Claims_SingleSource_v1.3.csv")
    parser.add_argument('--measure', type=str, default=None, action= 'append',help='MeasureId to be evaluated (optional)')
    parser.add_argument('--output', type=str, help= 'output path (optional)', default="tests/single_source_csv/csv_report")
    args = parser.parse_args()

    # Method to use pipenv run python <script> <Optional: Measure ID to be checked>
    # Change these files wherenver needed
    basefilename = args.base
    newfilename = args.new
    output = args.output

    basefile = pd.read_csv(basefilename, dtype=str)
    newfile = pd.read_csv(newfilename, dtype=str)
    

    basefile.columns = basefile.columns.str.replace(' ', '_')
    newfile.columns = newfile.columns.str.replace(' ', '_')
    # Version to capture
    basefile["VERSION"] = "BASE"
    newfile["VERSION"] = "NEW"
    # Const to capture the whole file
    basefile["CONST"] = "CONST"
    newfile["CONST"] = "CONST"

    key = newfile.columns.values.tolist()
    key.remove("VERSION")
    joint = newfile.merge(basefile, on=key, how="outer", suffixes=["_new", "_base"])

    pd.set_option('display.max_rows', None)
    pd.set_option('expand_frame_repr', False)

    joint["VERSION"] = joint.apply(getJoinMeta, axis=1)
    joint = joint.drop(["VERSION_new", "VERSION_base"], axis=1)[['VERSION',
                                                                 'Measure_ID',
                                                                 'DATA_ELEMENT_NAME',
                                                                 'CODING_SYSTEM',
                                                                 'CODE',
                                                                 'MODIFIER',
                                                                 'PLACE_OF_SERVICE',
                                                                 'AGE',
                                                                 'GENDER',
                                                                 'CONST']]


    onlybase = joint[joint.VERSION == "BASE"]
    onlynew = joint[joint.VERSION == "NEW"]
    intersection = joint[joint.VERSION == "COMMON"]

    # Main function
    os.makedirs(output, exist_ok=True)
    (df, modified_mid, added_mid, removed_mid, changed_mid) = analyze_difference(joint, "CONST", "CONST", "Measure_ID")

    mid = {}

    modified_den = {}
    added_den = {}
    changed_den = {}
    removed_den = {}

    with open(output+"/Summary.md", "w") as f:
        print("# Single Source changes Summary", file=f)
        print("Basefile = " + os.path.basename(basefilename), file=f)
        print("newfile =" + os.path.basename(newfilename), file=f)
        paragraph(f)
        print("## Analysis at file level", file=f)
        print("Base rows only", file=f)
        print(len(onlybase), file=f)
        print("new rows only", file=f)
        print(len(onlynew), file=f)
        print("common rows only", file=f)
        print(len(intersection), file=f)
        paragraph(f)
        print("## Analysis at Measure ID Level level", file=f)
        print("*Added Measures*:" + str(len(added_mid)), file=f)
        print("*Removed Measures*:" + str(len(removed_mid)), file=f)
        print("*Changed Measures*:" + str(len(changed_mid)), file=f)
        print("## Details at Measure ID Level level", file=f)
        print("*Added Measures*:" + str(added_mid), file=f)
        print("*Removed Measures*:" + str(removed_mid), file=f)
        print("*Changed Measures*:" + str(changed_mid), file=f)

    report_mid = modified_mid
    def intersection(lst1, lst2):
        lst3 = [value for value in lst1 if value in lst2]
        return lst3

    if args.measure:
        report_mid = intersection(modified_mid,args.measure)
        print("running report for measures:"+str(report_mid))
    else:
        print("running report for all measures")

    for i in report_mid:
        filename = output+"/Measure" + i.zfill(3) + ".md"
        with open(filename, "w") as f:
            print("# Comparison for Measure ID " + i + "", file=f)
            (mid[i], modified_den[i], added_den[i], removed_den[i], changed_den[i]) = analyze_difference(df, "Measure_ID",
                                                                                                         i,
                                                                                                         "DATA_ELEMENT_NAME",
                                                                                                         False)
            den = {}
            modified_code = {}
            added_code = {}
            removed_code = {}
            changed_code = {}

            print("Data Element Name Summary", file=f)
            print("*Added DEN*:" + str(added_den[i]), file=f)
            print("*Removed DEN*:" + str(removed_den[i]), file=f)
            print("*Changed DEN*:" + str(changed_den[i]), file=f)

            for j in added_den[i]:
                print("## For ADDED Data Element name " + j, file=f)
                (den[j], modified_code[j], added_code[j], removed_code[j], changed_code[j]) = analyze_difference(mid[i],
                                                                                                                 "DATA_ELEMENT_NAME",
                                                                                                                 j, "CODE")
                print("Codes Summary", file=f)
                print("*Number of CODES*:" + str(len(added_code[j])), file=f)

                print("### Codes added as part of Data Element", file=f)
                printDf(den[j][den[j]["CODE"].isin(added_code[j])], f)

            for j in removed_den[i]:
                print("## For REMOVED Data Element name " + j, file=f)
                (den[j], modified_code[j], added_code[j], removed_code[j], changed_code[j]) = analyze_difference(mid[i],
                                                                                                                 "DATA_ELEMENT_NAME",
                                                                                                                 j, "CODE")
                print("Codes Summary", file=f)
                print("* Number of CODES*:" + str(len(removed_code[j])), file=f)

                print("### Codes REMOVED as part of Data Element", file=f)
                printDf(den[j][den[j]["CODE"].isin(removed_code[j])], f)

            for j in changed_den[i]:

                print("## For Data Element Name " + j, file=f)
                (den[j], modified_code[j], added_code[j], removed_code[j], changed_code[j]) = analyze_difference(mid[i],
                                                                                                                 "DATA_ELEMENT_NAME",
                                                                                                                 j, "CODE")
                print("Codes Summary", file=f)
                print("* Number of Added CODES*:" + str(len(added_code[j])), file=f)
                print("* Number of Removed CODES*:" + str(len(removed_code[j])), file=f)
                print("* Number of Changed CODES*:" + str(len(changed_code[j])), file=f)

                if (len(added_code[j]) > 0):
                    print("### Added Codes", file=f)
                    printDf(den[j][den[j]["CODE"].isin(added_code[j])], f)
                if (len(removed_code[j]) > 0):
                    print("### Removed Codes", file=f)
                    printDf(den[j][den[j]["CODE"].isin(removed_code[j])], f)
                if (len(changed_code[j]) > 0):
                    print("### Changed Codes", file=f)
                    printDf(den[j][den[j]["CODE"].isin(changed_code[j])], f)
