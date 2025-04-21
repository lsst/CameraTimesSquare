import click
import collections
import json
import re
import sys

from lsst.daf.butler import Butler
from lsst.resources import ResourcePath

CONFIG = {
    "LSSTCam": {
        "bucket": "embargo@rubin-summit",
        "butler_alias": "embargo_new",
        "obs_prefix": "MC",
    },
    "LSSTComCam": {
        "bucket": "embargo@rubin-summit",
        "butler_alias": "embargo_new",
        "obs_prefix": "CC",
    },
    "LATISS": {
        "bucket": "embargo@rubin-summit",
        "butler_alias": "embargo_new",
        "obs_prefix": "AT",
    },
}


@click.command()
@click.argument("instrument", required=True, type=click.Choice(list(CONFIG.keys())))
@click.argument("dayobs", type=int, required=True)
def run(instrument: str, dayobs: int):
    main(instrument, dayobs)


def diff(expected_set, found_set, ingested_set):
    for det in sorted(expected_set):
        if det not in found_set:
            print(f"{det} not sent")
        elif det not in ingested_set:
            print(f"{det} not ingested")
    for det in sorted(found_set):
        if det not in expected_set and det not in ingested_set:
            print(f"{det} unexpected, not ingested")
    for det in sorted(ingested_set):
        if det not in found_set:
            print(f"{det} ingested but not found")


def main(instrument, dayobs):
    bucket = CONFIG[instrument]["bucket"]
    butler_alias = CONFIG[instrument]["butler_alias"]
    obs_prefix = CONFIG[instrument]["obs_prefix"]

    day_path = ResourcePath(f"s3://{bucket}/{instrument}/{dayobs}/")
    for dirpath, dirnames, filenames in day_path.walk():
        if len(dirnames) > 0:
            max_seq = int(sorted(dirnames)[-1][-7:-1])
            break
    else:
        print(f"No data on {dayobs}")
        sys.exit(1)

    butler = Butler(
        butler_alias, instrument=instrument, collections=f"{instrument}/raw/all"
    )

    detector_dict = {
        x.id: x.full_name
        for x in butler.query_dimension_records("detector", instrument=instrument)
    }

    ingested_detectors = collections.defaultdict(set)
    with butler.query() as q:
        for data_id in (
            q.where(f"day_obs={dayobs}")
            .join_dataset_search("raw")
            .data_ids(["exposure", "detector"])
        ):
            ingested_detectors[data_id["exposure"] % 100000].add(
                detector_dict[data_id["detector"]]
            )

    for seqnum in range(1, max_seq + 1):
        print(f"{dayobs=} {seqnum=}", end="")
        expected_detectors = set(detector_dict.values())
        expected_present = False
        expected_guiders = set()
        found_detectors = set()
        found_guiders = set()
        found = False
        for controller in ("O", "C", "P", "S"):
            obs_id = f"{obs_prefix}_{controller}_{dayobs}_{seqnum:06d}"
            obs_path = day_path.join(obs_id, forceDirectory=True)
            filenames = []
            for dirpath, dirnames, filenames in obs_path.walk():
                break
            if len(filenames) == 0:
                continue
            es_name = f"{obs_id}_expectedSensors.json"
            if es_name in filenames:
                expected_present = True
                es_path = dirpath.join(es_name)
                expected_sensors = json.loads(es_path.read())["expectedSensors"]
                expected_detectors = {
                    d for d in expected_sensors if expected_sensors[d] == "SCIENCE"
                }
                expected_guiders = {
                    d for d in expected_sensors if expected_sensors[d] == "GUIDER"
                }

            for f in filenames:
                if f.endswith(".fits"):
                    m = re.search(r"R[0-4][0-4]_S[0-4GW][0-4]", f)
                    detector = m.group(0)
                    if f.endswith("_guider.fits"):
                        found_guiders.add(detector)
                    else:
                        found_detectors.add(detector)

            break

        else:
            print(" NOT TAKEN?")
            continue

        expect_s = len(expected_detectors)
        expect_g = len(expected_guiders)
        found_s = len(found_detectors)
        found_g = len(found_guiders)
        ingest_s = len(ingested_detectors[seqnum])

        print(
            f" {expect_s=} {expect_g=} {found_s=} {found_g=} {ingest_s=}{'' if expected_present else ' !'}",
            end="",
        )

        if found_s < ingest_s:
            print(" IMPOSSIBLE")
        elif found_s > ingest_s:
            if found_s < expect_s:
                print(" NOT SENT + NOT INGESTED")
            else:
                if ingest_s == 0:
                    print(" NONE INGESTED")
                    continue
                else:
                    print(" NOT INGESTED")
        else: # found_s == ingest_s
            if found_s < expect_s:
                if ingest_s == 0:
                    print(" NONE SENT")
                    continue
                else:
                    print(" SOME MISSING")
            elif found_s > expect_s:
                print(" ?OK")
                continue
            else: # found_s == expect_s
#                print(" OK")
                continue

        diff(expected_detectors, found_detectors, ingested_detectors[seqnum])


if __name__ == "__main__":
    run()
