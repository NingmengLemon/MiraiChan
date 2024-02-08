from . import operator_lib
# import operator_lib

import random
import copy
import logging

total_lib = []
fastdict_standard_by_star = {}
fastdict_backbone_by_star = {}


def init():
    global fastdict_standard_by_star
    global fastdict_backbone_by_star
    global total_lib
    total_lib = operator_lib.get_nowait()
    logging.debug("data loaded, %d operators in total"%len(total_lib))
    fastdict_standard_by_star = {i: [] for i in range(3, 6 + 1)}
    fastdict_backbone_by_star = {i: [] for i in range(3, 6 + 1)}
    for i in total_lib:
        star = i["star"]
        if star in range(3, 6 + 1) and "标准寻访" in i["pool"]:
            fastdict_standard_by_star[star].append(i)
        if star in range(3, 6 + 1) and "中坚寻访" in i["pool"]:
            fastdict_backbone_by_star[star].append(i)
    logging.debug("fast-query dict generated")


def random_with_weight(data_dict):
    sum_wt = sum(data_dict.values())
    ra_wt = random.uniform(0, sum_wt)
    cur_wt = 0
    for key in data_dict.keys():
        cur_wt += data_dict[key]
        if ra_wt <= cur_wt:
            return key

def gacha(combo: int = 1):
    probas = {
        3: 0.4,
        4: 0.5,
        5: 0.08,
        6: 0.02,
    }
    if combo > 50 and combo < 100:
        offset = 0.02 * (combo - 50)
        offset = min(probas[6] + offset, 1) - probas[6]
        probas[6] += offset
        decrease_per_star = offset / 3
        for star in [3, 4, 5]:
            probas[star] -= decrease_per_star
            probas[star] = max(probas[star], 0)
    elif combo >= 100:
        return 6
    return random_with_weight(probas)


def gacha_standard(combo: int = 0):
    return copy.deepcopy(random.choice(fastdict_standard_by_star[gacha(combo)]))


def gacha_backbone(combo: int = 0):
    return copy.deepcopy(random.choice(fastdict_backbone_by_star[gacha(combo)]))


if __name__ == "__main__":
    init()
    combo = 0
    for i in range(100):
        op = gacha_standard(combo)
        if op["star"] == 6:
            combo = 0
        print("%3d %d %s" % (i + 1, op["star"], op["name"]), sep="\t")
