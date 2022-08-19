def hanzi2number(numS):
    numDict = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6,'七': 7, '八': 8, '九': 9, "零" : 0}
    num = 0
    if "百" in numS:
        indexB = numS.index("百");
        value = numS[0:indexB];
        num = numDict[value] * 100;
        if "十" in numS:
            indexS = numS.index("十");
            value = numS[indexB+1:indexS]
            if len(value) == 0:
                value = "一"
            num = num + 10 * numDict[value];
            value = numS[indexS+1:];
            if len(value) > 0:
                num = num + numDict[value];
        else:
            if "零" in numS:
                indexB = indexB + 1;
            value = numS[indexB+1:]
            if len(value) > 0:
                num = num + numDict[value];
    else:
        if "十" in numS:
            indexS = numS.index("十");
            value = numS[0:indexS];
            if len(value) == 0:
                value = "一"
            num = num + 10 * numDict[value];
            value = numS[indexS+1:];
            if len(value) > 0:
                num = num + numDict[value];
        else:
            num = numDict[numS];
    return num;
