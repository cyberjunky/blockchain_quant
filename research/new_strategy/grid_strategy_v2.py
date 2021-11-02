# encoding=utf-8

from threading import Thread
from tools.Config import Cancel_url, amountlimit, premiumdict, Trade_url, Queryorder_url, Query_tradeprice_url, \
    pricelimit
from tools.get_market_info import *
from tools.databasePool import r2, POOL_grid
from loggerConfig import logger


def base_usertrade_info(griddata):
    global userUuid, apiAccountId, strategyId, platform, symbol, entryPrice, counterCoinName, valueCoinName
    global gap, makerFee, count, highprice, lowprice
    userUuid = griddata['userUuid']
    apiAccountId = griddata['apiAccountId']
    strategyId = griddata['strategyId']
    platform = griddata['platform']
    symbol = griddata['symbol']
    entryPrice = griddata["entryPrice"]  # 入场价格
    counterCoinName = symbol.split("_")[0]  # 交易币
    valueCoinName = symbol.split("_")[1]  # 计价币
    gap = griddata["gridSpacing"]  # 网格间距
    makerFee = griddata["makerFee"]  # 挂单手续费
    count = griddata["minTradeQuantity"]  # 每次下单量
    highprice = griddata["profitCeiling"]  # 止盈位
    lowprice = griddata["stopLossPrice"]  # 支撑位，止损


# 撤销网格单
def cancelgridorders(orderid, sellorderlist, buyorderlist):
    conn = POOL_grid.connection()
    cur = conn.cursor()
    try:
        if orderid in sellorderlist:
            res = requests.post(Cancel_url, data={"direction": 2, "symbol": symbol, "platform": platform,
                                                  "orderId": orderid, "apiAccountId": apiAccountId,
                                                  "userUuid": userUuid,
                                                  "source": 4, "strategyId": strategyId, "icebergId": strategyId})
            cur.execute("update t_gridtrade set sellstatus=2 where strategyId=%s and sellorderid=%s",
                        (strategyId, orderid))
        if orderid in buyorderlist:
            res = requests.post(Cancel_url, data={"direction": 1, "symbol": symbol, "platform": platform,
                                                  "orderId": orderid, "apiAccountId": apiAccountId,
                                                  "userUuid": userUuid,
                                                  "source": 4, "strategyId": strategyId, "icebergId": strategyId})
            cur.execute("update t_gridtrade set buystatus=2 where strategyId=%s and buyorderid=%s",
                        (strategyId, orderid))
    except Exception as e:
        i = "系统正在为用户{}撤销{}平台订单{}出错{}".format(userUuid, platform, orderid, e)
        logger.error(i)
    finally:
        conn.commit()
        cur.close()
        conn.close()


# 平仓处理
def clear_grid_remain(amount):
    try:
        print("==============================下单======================================")
        amount = amount
        try:
            x, y = str(amount).split('.')
            amount = float(x + '.' + y[0:amountlimit[symbol][platform]])
        except Exception as e:
            info = "单笔下单量为整数，无需截取小数位"
            print(info)
        current_price = get_currentprice1(platform, symbol)
        price = current_price - premiumdict[symbol]
        tradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        tradeparams = {"direction": 2, "amount": amount, "symbol": symbol, "platform": platform, "price": price,
                       "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4, "strategyId": strategyId,
                       "uniqueId": 2, "icebergId": strategyId}
        traderes = requests.post(Trade_url, data=tradeparams)
        trade_dict = json.loads(traderes.content.decode())
        orderid = trade_dict["response"]["orderid"]  # 获取订单id

        print("=================================查询===================================")
        queryparams = {"direction": 2, "symbol": symbol, "platform": platform, "orderId": orderid,
                       "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4, "strategyId": strategyId,
                       "icebergId": strategyId}
        res = requests.post(Queryorder_url, data=queryparams)
        queryresdict = json.loads(res.content.decode())
        numberDeal = float(queryresdict["response"]["numberDeal"])
        try:
            queryparams = {"platform": platform, "symbol": symbol, "orderId": orderid, "apiId": apiAccountId,
                           "userUuid": userUuid}
            res = requests.post(Query_tradeprice_url, data=queryparams)
            queryresdict = json.loads(res.content.decode())
            if queryresdict["response"]["avgPrice"] != None:
                price = queryresdict["response"]["avgPrice"]
            if queryresdict["response"]["createdDate"] != None:
                tradetime = queryresdict["response"]["createdDate"]
        except Exception as e:
            pass
        print("================================撤单====================================")
        cancelparams = {"direction": 2, "symbol": symbol, "platform": platform, "orderId": orderid,
                        "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4, "strategyId": strategyId,
                        "icebergId": strategyId}
        requests.post(Cancel_url, data=cancelparams)

        conn = POOL_grid.connection()
        cur = conn.cursor()
        sellinsertsql = "insert into t_gridtrade (userUuid,apiAccountId,strategyId,platform,symbol,sellprice,sellcount,sellorderid,sellstatus,sellordertime,uniqueId) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
        cur.execute(sellinsertsql,
                    (userUuid, apiAccountId, strategyId, platform, symbol, price, numberDeal, orderid, 1, tradetime, 3))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        errorinfo = "策略{}停止平仓时出错{}".format(strategyId, e)
        logger.error(errorinfo)


#  网格部署(含密度)
def gridbegin(griddata):
    info1 = "量化策略{}正在部署初始网格单...".format(strategyId)
    print(info1)
    costBuyprice = griddata["entryPrice"]  # 买入成本价
    gap = griddata["gridSpacing"]  # 网格间距
    makerFee = griddata["makerFee"]  # 挂单手续费
    density = gap / 2  # 网格密度
    count = griddata["minTradeQuantity"]  # 每次交易量
    # 开始部署网格
    try:
        conn = POOL_grid.connection()
        cur = conn.cursor()
        # 1、往上部署一个卖单
        sellprice = round((costBuyprice + gap), pricelimit[symbol][platform])
        sell_dict = {"direction": 2, "amount": count, "symbol": symbol, "platform": platform, "price": sellprice,
                     "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4, "strategyId": strategyId,
                     "icebergId": strategyId}
        res_sell = requests.post(Trade_url, data=sell_dict)
        trade_sell_dict = json.loads(res_sell.content.decode())
        # logger.info("网格{}初始化部署卖单{}".format(strategyId, trade_sell_dict))
        sellorderid = trade_sell_dict["response"]["orderid"]  # 获取订单id
        info2 = "卖单1委托成功，交易平台：{}，价格：{}，数量{}".format(platform, sellprice, count)
        print(info2)
        profit = gap * count
        netprofit = profit - costBuyprice * count * makerFee - sellprice * count * makerFee
        sellordertime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        sellinsertsql = "insert into t_gridtrade (userUuid,apiAccountId,strategyId,platform,symbol,sellprice,sellcount,sellorderid,sellstatus,sellordertime,profit,netprofit,uniqueId) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
        cur.execute(sellinsertsql,
                    (userUuid, apiAccountId, strategyId, platform, symbol, sellprice, count, sellorderid, 0,
                     sellordertime, profit, netprofit, 1))
        selldata = {"userUuid": userUuid, "apiAccountId": apiAccountId, "strategyId": strategyId, "platform": platform,
                    "symbol": symbol,
                    "count": count, "sellprice": sellprice, "sellorderid": sellorderid}
        key_sell = "grid:sell:" + str(strategyId) + ":0"
        r2.set(key_sell, json.dumps(selldata))  # 存入redis数据库
        # 2、往下部署一个买单
        buyprice = round((costBuyprice - gap), pricelimit[symbol][platform])
        buy_dict = {"direction": 1, "amount": count, "symbol": symbol, "platform": platform,
                    "price": buyprice, "apiAccountId": apiAccountId, "userUuid": userUuid,
                    "source": 4, "strategyId": strategyId, "icebergId": strategyId}
        res_buy = requests.post(Trade_url, data=buy_dict)
        trade_buy_dict = json.loads(res_buy.content.decode())
        # logger.info("网格{}初始化部署买单{}".format(strategyId, trade_buy_dict))
        buyorderid = trade_buy_dict["response"]["orderid"]  # 获取订单id
        info3 = "买单1委托成功，交易平台{}，价格：{}，数量{}".format(platform, buyprice, count)
        buyordertime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        buyinsertsql = "insert into t_gridtrade (userUuid,apiAccountId,strategyId,platform,symbol,buyprice,buycount,buyorderid,buystatus,buyordertime,uniqueId) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
        cur.execute(buyinsertsql, (
            userUuid, apiAccountId, strategyId, platform, symbol, buyprice, count, buyorderid, 0, buyordertime, 1))
        buydata = {"userUuid": userUuid, "apiAccountId": apiAccountId, "strategyId": strategyId, "platform": platform,
                   "symbol": symbol,
                   "count": count, "buyprice": buyprice, "buyorderid": buyorderid}
        key_buy = "grid:buy:" + str(strategyId) + ":0"
        r2.set(key_buy, json.dumps(buydata))
        # 3、下密度卖单
        sellprice1 = round((costBuyprice + density), pricelimit[symbol][platform])
        sell_dict1 = {"direction": 2, "amount": count, "symbol": symbol, "platform": platform,
                      "price": sellprice1, "apiAccountId": apiAccountId, "userUuid": userUuid,
                      "source": 4, "strategyId": strategyId, "icebergId": strategyId}
        res_sell1 = requests.post(Trade_url, data=sell_dict1)
        trade_sell_dict1 = json.loads(res_sell1.content.decode())
        # logger.info("网格{}初始化部署密度卖单{}".format(strategyId, trade_sell_dict1))
        print(sell_dict1)
        print("****卖", trade_sell_dict1)
        sellorderid1 = trade_sell_dict1["response"]["orderid"]  # 获取订单id
        info4 = "卖单2委托成功，交易平台{}，价格{}，数量{}".format(platform, sellprice1, count)
        print(info4)
        profit1 = density * count
        netprofit1 = profit1 - sellprice1 * count * makerFee
        sellordertime1 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        cur.execute(sellinsertsql, (
            userUuid, apiAccountId, strategyId, platform, symbol, sellprice1, count, sellorderid1, 0, sellordertime1,
            profit1, netprofit1, 1))
        # 4、下密度买单
        buyprice1 = round((costBuyprice - density), pricelimit[symbol][platform])
        buy_dict1 = {"direction": 1, "amount": count, "symbol": symbol, "platform": platform,
                     "price": buyprice1, "apiAccountId": apiAccountId, "userUuid": userUuid,
                     "source": 4, "strategyId": strategyId, "icebergId": strategyId}
        res_buy1 = requests.post(Trade_url, data=buy_dict1)
        trade_buy_dict1 = json.loads(res_buy1.content.decode())
        # logger.info("网格{}初始化部署密度买单{}".format(strategyId, trade_buy_dict1))
        print(buy_dict1)
        print("****买", trade_buy_dict1)
        buyorderid1 = trade_buy_dict1["response"]["orderid"]  # 获取订单id
        info5 = "买单2委托成功，交易平台{}，价格：{}，数量{}".format(platform, buyprice1, count)
        print(info5)
        # r.lpush("gridinfo:{}".format(userId), info5)  # 信息存储到redis
        # 4、将买单存入数据库和内存
        buyordertime1 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        cur.execute(buyinsertsql, (
            userUuid, apiAccountId, strategyId, platform, symbol, buyprice1, count, buyorderid1, 0, buyordertime1, 1))
        orderdata = {"userUuid": userUuid, "apiAccountId": apiAccountId, "strategyId": strategyId, "platform": platform,
                     "symbol": symbol,
                     "count": count, "buyprice": buyprice1, "buyorderid": buyorderid1,
                     "sellprice": sellprice1, "sellorderid": sellorderid1}
        key = "grid:init:" + str(strategyId)
        r2.set(key, json.dumps(orderdata))  # 存入redis数据库
        conn.commit()
        cur.close()
        conn.close()
        return 1
    except Exception as e:
        i = "用户{}，初步部署网格策略{}，报错信息{}".format(userUuid, strategyId, e)
        print(i)
        logger.error(i)
        return 0


#  量化策略2网格部署（无密度单）
def gridbegin2(griddata):
    info1 = "量化策略2{}正在部署初始网格单...".format(strategyId)
    print(info1)
    apiAccountId = griddata["apiAccountId"]
    platform = griddata["platform"]
    symbol = griddata["symbol"]
    costBuyprice = griddata["entryPrice"]  # 买入成本价
    gap = griddata["gridSpacing"]  # 网格间距
    makerFee = griddata["makerFee"]  # 挂单手续费
    count = griddata["minTradeQuantity"]  # 每次交易量
    # 开始部署网格
    try:
        conn = POOL_grid.connection()
        cur = conn.cursor()
        # 1、往上部署一个卖单
        sellprice = round((costBuyprice + gap), pricelimit[symbol][platform])
        sell_dict = {"direction": 2, "amount": count, "symbol": symbol, "platform": platform,
                     "price": sellprice, "apiAccountId": apiAccountId, "userUuid": userUuid,
                     "source": 4, "strategyId": strategyId, "icebergId": strategyId}
        res_sell = requests.post(Trade_url, data=sell_dict)
        trade_sell_dict = json.loads(res_sell.content.decode())
        trade_sell_info = "网格{}初始化部署卖单{}".format(strategyId, trade_sell_dict)
        print(trade_sell_info)
        # logger.info(trade_sell_info)
        sellorderid = trade_sell_dict["response"]["orderid"]  # 获取订单id
        info2 = "卖单1委托成功，交易平台：{}，价格：{}，数量{}".format(platform, sellprice, count)
        print(info2)
        profit = gap * count
        netprofit = profit - costBuyprice * count * makerFee - sellprice * count * makerFee
        sellordertime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        sellinsertsql = "insert into t_gridtrade (userUuid,apiAccountId,strategyId,platform,symbol,sellprice,sellcount,sellorderid,sellstatus,sellordertime,profit,netprofit,uniqueId) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
        cur.execute(sellinsertsql,
                    (userUuid, apiAccountId, strategyId, platform, symbol, sellprice, count, sellorderid, 0,
                     sellordertime, profit, netprofit, 1))
        selldata = {"userUuid": userUuid, "apiAccountId": apiAccountId, "strategyId": strategyId, "platform": platform,
                    "symbol": symbol,
                    "count": count, "sellprice": sellprice, "sellorderid": sellorderid}
        key_sell = "grid2:sell:" + str(strategyId)
        r2.set(key_sell, json.dumps(selldata))  # 存入redis数据库
        # 2、往下部署一个买单
        buyprice = round((costBuyprice - gap), pricelimit[symbol][platform])
        buy_dict = {"direction": 1, "amount": count, "symbol": symbol, "platform": platform, "price": buyprice,
                    "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4, "strategyId": strategyId,
                    "icebergId": strategyId}
        res_buy = requests.post(Trade_url, data=buy_dict)
        trade_buy_dict = json.loads(res_buy.content.decode())
        # logger.info("网格{}初始化部署买单{}".format(strategyId, trade_buy_dict))
        buyorderid = trade_buy_dict["response"]["orderid"]  # 获取订单id
        info3 = "买单1委托成功，交易平台{}，价格：{}，数量{}".format(platform, buyprice, count)
        print(info3)
        # r.lpush("gridinfo:{}".format(userId), info3)  # 信息存储到redis
        buyordertime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        buyinsertsql = "insert into t_gridtrade (userUuid,apiAccountId,strategyId,platform,symbol,buyprice,buycount,buyorderid,buystatus,buyordertime,uniqueId) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
        cur.execute(buyinsertsql, (
            userUuid, apiAccountId, strategyId, platform, symbol, buyprice, count, buyorderid, 0, buyordertime, 1))
        buydata = {"userUuid": userUuid, "apiAccountId": apiAccountId, "strategyId": strategyId, "platform": platform,
                   "symbol": symbol,
                   "count": count, "buyprice": buyprice, "buyorderid": buyorderid}
        key_buy = "grid2:buy:" + str(strategyId)
        r2.set(key_buy, json.dumps(buydata))
        conn.commit()
        cur.close()
        conn.close()
        return 1
    except Exception as e:
        i = "用户{}，初步部署网格策略{}，报错信息{}".format(userUuid, strategyId, e)
        print(i)
        logger.error(i)
        return 0


def buyorderquery(grid_orders):
    buyquerydict = {}
    buynum = 0
    try:
        buy_query = {"direction": 1, "symbol": symbol, "platform": platform,
                     "orderId": grid_orders["buyorderid"],
                     "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4,
                     "strategyId": strategyId, "icebergId": strategyId}
        buyqueryres = requests.post(Queryorder_url, data=buy_query)
        buyquerydict = json.loads(buyqueryres.content.decode())
        buynum = float(buyquerydict["response"]["numberDeal"])
        print("用户", userUuid, "，交易平台：", platform, "密度买单订单号：", grid_orders["buyorderid"], "价格：",
              grid_orders["buyprice"], ",已成交量：", buynum)
    except Exception as e:
        i = "用户{}网格策略{}交易平台{}查询订单出错{},{}".format(userUuid, strategyId, platform, e, buyquerydict)
        print(i)
        logger.error(i)
    else:
        return buynum


def sellorderquery(grid_orders):
    sellquerydict = {}
    sellnum = 0
    try:
        sell_query = {'direction': 2, 'symbol': symbol, 'platform': platform,
                      'orderId': grid_orders['sellorderid'],
                      'apiAccountId': apiAccountId, 'userUuid': userUuid, 'source': 4,
                      'strategyId': strategyId, 'icebergId': strategyId}
        sellqueryres = requests.post(Queryorder_url, data=sell_query)
        sellquerydict = json.loads(sellqueryres.content.decode())
        sellnum = float(sellquerydict['response']['numberDeal'])
        print("用户", userUuid, "，交易平台：", platform, "密度卖单订单号：", grid_orders["sellorderid"], "价格：",
              grid_orders["sellprice"], ",已成交量：", sellnum)
    except Exception as e:
        i = "用户{}网格策略{}交易平台{}查询订单出错{},{}".format(userUuid, strategyId, platform, e, sellquerydict)
        print(i)
        logger.error(i)
    else:
        return sellnum


def cancerbuyorder(grid_orders, cur):
    cancelres1 = requests.post(Cancel_url,
                               data={"direction": 1, "symbol": symbol, "platform": platform,
                                     "orderId": grid_orders["buyorderid"],
                                     "apiAccountId": apiAccountId,
                                     "userUuid": userUuid, "source": 4, "strategyId": strategyId,
                                     "icebergId": strategyId})
    cancelinfo1 = "用户{}策略{}平台{}撤销买单，返回结果{}".format(userUuid, strategyId, platform, cancelres1.text)
    logger.info(cancelinfo1)
    deletesellsql = "delete from t_gridtrade where strategyId=%s and buyorderid=%s"
    cur.execute(deletesellsql, (strategyId, grid_orders["buyorderid"]))


def cancersellorder(grid_orders, cur):
    cancelres1 = requests.post(Cancel_url,
                               data={"direction": 2, "symbol": symbol, "platform": platform,
                                     "orderId": grid_orders["sellorderid"],
                                     "apiAccountId": apiAccountId,
                                     "userUuid": userUuid, "source": 4, "strategyId": strategyId,
                                     "icebergId": strategyId})
    cancelinfo1 = "用户{}策略{}平台{}撤销卖单，返回结果{}".format(userUuid, strategyId, platform, cancelres1.text)
    logger.info(cancelinfo1)
    deletesellsql = "delete from t_gridtrade where strategyId=%s and sellorderid=%s"
    cur.execute(deletesellsql, (strategyId, grid_orders["sellorderid"]))


def restingneworder(finishprice, cur, grid_order):  # 挂新的买卖单
    buytradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    newsellprice = round((finishprice + gap), pricelimit[symbol][platform])
    newsellordertime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    newsellparams = {"direction": 2, "amount": count, "symbol": symbol, "platform": platform,
                     "price": newsellprice,
                     "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4,
                     "strategyId": strategyId, "icebergId": strategyId}
    res2 = requests.post(Trade_url, data=newsellparams)
    dict2 = json.loads(res2.content.decode())
    i = "用户{}策略{}平台{}新挂卖单{}".format(userUuid, strategyId, platform, dict2)
    # logger.info(i)
    print(i)
    sellcode = dict2["code"]  # 卖单状态
    if sellcode != 1:
        sellerrorinfo = "您的{}平台{}资金不足或者交易所接口不通，导致网格策略下卖单失败，请停止当前策略，可在调整资金后再重新创建开启".format(platform,
                                                                                          counterCoinName)
        print(sellerrorinfo)
        # 资产不足信息储存到redis
        remainerrordata = {"strategyId": strategyId, "apiAccountId": apiAccountId,
                           "userUuid": userUuid, "platform": platform,
                           "coin": counterCoinName,
                           "marktime": int(time.time() * 1000)}
        r2.hset("errormark", strategyId, json.dumps(remainerrordata))
    elif sellcode == 1:
        newsellorderid = dict2["response"]["orderid"]
        profit = gap * count
        netprofit = profit - (newsellprice - gap) * count * makerFee - newsellprice * count * \
                    makerFee
        updatesql1 = "update t_gridtrade set buystatus=%s,buytradetime=%s,sellprice=%s,sellcount=%s,sellorderid=%s,sellstatus=%s,sellordertime=%s,profit=%s,netprofit=%s where strategyId=%s and buyorderid=%s "
        cur.execute(updatesql1, (
            1, buytradetime, newsellprice, count, newsellorderid, 0, newsellordertime, profit,
            netprofit,
            strategyId, grid_order["buyorderid"]))
        # 3、新挂一个买单（比之前的买单小一个网格）
        newbuyprice = round((finishprice - gap), pricelimit[symbol][platform])
        newbuyordertime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        newbuyparams = {"direction": 1, "amount": count, "symbol": symbol, "platform": platform,
                        "price": newbuyprice,
                        "apiAccountId": apiAccountId, "userUuid": userUuid, "source": 4,
                        "strategyId": strategyId, "icebergId": strategyId}
        res1 = requests.post(Trade_url, data=newbuyparams)
        dict1 = json.loads(res1.content.decode())
        i = "用户{}策略{}平台{}新挂买单{}".format(userUuid, strategyId, platform, dict1)
        # logger.info(i)
        print(i)
        buycode = dict1["code"]
        if buycode != 1:
            buyerrorinfo = "您的{}平台{}资金不足或者交易所接口不通，导致网格策略下买单失败，请停止当前策略，可在调整资金后再重新创建开启".format(
                platform,
                valueCoinName)
            print(buyerrorinfo)
            # logger.info(buyerrorinfo)
            # r.lpush("gridinfo:{}".format(userId), buyerrorinfo)  # 信息存储到redis
            # 资产不足信息储存到redis
            remainerrordata = {"strategyId": strategyId, "apiAccountId": apiAccountId,
                               "userUuid": userUuid, "platform": platform,
                               "coin": valueCoinName,
                               "marktime": int(time.time() * 1000)}
            r2.hset("errormark", strategyId, json.dumps(remainerrordata))
        elif buycode == 1:
            newtradeinfo = "量化策略{}部署新的网格订单，卖单价{}，买单价{}".format(strategyId, newsellprice,
                                                               newbuyprice)
            # r.lpush("gridinfo:{}".format(userId), newtradeinfo)  # 信息存储到redis
            newbuyorderid = dict1["response"]["orderid"]
            buyinsertsql = "insert into t_gridtrade (userUuid,apiAccountId,strategyId,platform,symbol,buyprice,buycount,buyorderid,buystatus,buyordertime,uniqueId) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
            cur.execute(buyinsertsql, (
                userUuid, apiAccountId, strategyId, platform, symbol, newbuyprice, count,
                newbuyorderid, 0, newbuyordertime, 1))
            # 4、修改内存中订单信息
            selldata = {"userUuid": userUuid, "apiAccountId": apiAccountId,
                        "strategyId": strategyId, "platform": platform,
                        "symbol": symbol,
                        "count": count, "sellprice": newsellprice, "sellorderid": newsellorderid}
            buydata = {"userUuid": userUuid, "apiAccountId": apiAccountId, "strategyId": strategyId,
                       "platform": platform,
                       "symbol": symbol,
                       "count": count, "buyprice": newbuyprice, "buyorderid": newbuyorderid}
            return selldata, buydata


def grid_strategy(griddata, currentpricelist):
    strategyType = griddata["strategyType"]
    base_usertrade_info(griddata)
    if strategyType == 1:
        currentprice = \
            [i["currentprice"] for i in currentpricelist if i["platform"] == platform and i["symbol"] == symbol][0]
        info = "量化策略{}正在执行中...".format(strategyId)
        print(info)
        grid_orders = json.loads(r2.get("grid:init:" + str(strategyId)))
        if currentprice == 0:  # 如果当前价为0，则取其他平台均价，如果其他平台也为0，则再取单个平台当前价
            currentpricelistnew = [i["currentprice"] for i in currentpricelist if
                                   i["symbol"] == symbol and i["currentprice"] != 0]
            if len(currentpricelistnew) != 0:
                currentprice = round(sum(currentpricelistnew) / len(currentpricelistnew),
                                     pricelimit[symbol][platform])
            else:
                currentprice = get_currentprice1(platform, symbol)
        if grid_orders != {}:  # 初始挂单后续操作
            print("正在查询网格策略{}初始密度单".format(strategyId))
            sellnum = sellorderquery(grid_orders)
            buynum = 0
            if sellnum != count:
                buynum = buyorderquery(grid_orders)
            elif sellnum == count:
                conn = POOL_grid.connection()
                cur = conn.cursor()
                try:
                    finishsellprice = grid_orders["sellprice"]  # 已经成交单的价格
                    info2 = "量化策略{}已成交一个卖单，交易平台{}，成交价{}，成交数量{}，正在为您部署新的网格...".format(strategyId, platform,
                                                                                     finishsellprice, sellnum)
                    print(info2)
                    # logger.info(info2)
                    # 1、改变卖单状态
                    selltradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    cur.execute(
                        'update t_gridtrade set sellstatus=%s,selltradetime=%s where strategyId=%s and sellorderid=%s',
                        (1, selltradetime, strategyId, grid_orders["sellorderid"]))
                    # 2、撤销买单grid_orders["buyorderid"]
                    cancerbuyorder(grid_orders, cur)
                    # 3、新挂一个卖单（比成交的卖单大一个网格，此时要注意余额是否足够)
                    selldata, buydata = restingneworder(finishsellprice, cur, grid_orders)
                    key_sell1 = "grid:sell:" + str(strategyId) + ":1"
                    key_buy1 = "grid:buy:" + str(strategyId) + ":1"
                    r2.set(key_sell1, json.dumps(selldata))
                    r2.set(key_buy1, json.dumps(buydata))
                    key = "grid:init:" + str(strategyId)
                    r2.set(key, json.dumps({}))  # 存入redis数据库
                except Exception as e:
                    i = "用户{}网格策略{}平台{}密度卖单成交进行下一步操作时出错{}".format(userUuid, strategyId, platform, e)
                    print(i)
                    logger.error(i)
                finally:
                    conn.commit()
                    cur.close()
                    conn.close()
                    # 调回状态
            elif buynum == count:
                try:
                    conn = POOL_grid.connection()
                    cur = conn.cursor()
                    finishbuyprice = grid_orders["buyprice"]
                    info3 = "量化策略{}已成交一个买单，交易平台{}，成交价{}，成交数量{}，正在为您部署新的网格...".format(strategyId, platform,
                                                                                     finishbuyprice, buynum)
                    # r.lpush("gridinfo:{}".format(userId), info3)  # 信息存储到redis
                    # logger.info(info3)
                    print(info3)
                    buytradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    # 1.撤销卖单
                    cancersellorder(grid_orders, cur)
                    # 2、新挂一个卖单,比最新成交价大一个网格区间
                    selldata0, buydata0 = restingneworder(finishbuyprice, cur, grid_orders)
                    key_sell0 = "grid:sell:" + str(strategyId) + ":0"
                    key_buy0 = "grid:buy:" + str(strategyId) + ":0"
                    key_sell1 = "grid:sell:" + str(strategyId) + ":1"
                    key_buy1 = "grid:buy:" + str(strategyId) + ":1"
                    selldata1 = r2.get(key_sell0)  # 交换位置
                    buydata1 = r2.get(key_buy0)
                    r2.set(key_sell0, json.dumps(selldata0))
                    r2.set(key_buy0, json.dumps(buydata0))
                    r2.set(key_sell1, selldata1)
                    r2.set(key_buy1, buydata1)
                except Exception as e:
                    i = "用户{}网格策略{}平台{}密度买单成交进行下一步操作时出错{}".format(userUuid, strategyId, platform, e)
                    print(i)
                    logger.error(i)
                finally:
                    conn.commit()
                    cur.close()
                    conn.close()
                    # 调回状态

        else:
            # 一、如果当前价小于等于止损价，止损出场
            if currentprice != 0 and currentprice <= lowprice + gap:  # 防止继续下单导致资金不足
                info1 = "行情到达止损价，暂停量化策略{}，您可以选择手动停止该策略，或者等待行情回调至网格区间继续运行。".format(strategyId)
                print(info1)
                # r.lpush("gridinfo:{}".format(userId), info1)
                pausetags = r2.hget("gridpausetags", strategyId)
                if pausetags != "1":  # 如果之前标记不为1，则发送短信提示，并将状态改为1
                    # res = requests.get(sendmessage_url, params={"userUuid": userUuid, "apiAccountId": apiAccountId,"strategyName": "量化", "runType": ""})
                    r2.hset("gridpausetags", strategyId, 1)
            # 二、如果当前价大于等于止盈价，止盈出场
            elif currentprice >= highprice - gap:  # 防止继续下单导致资金不足
                info2 = "行情上涨，已超出您的资金范围，暂停量化策略{}，您可以选择手动停止该策略，或者等待行情回调至网格区间继续运行。".format(strategyId)
                print(info2)
                # r.lpush("gridinfo:{}".format(userId), info2)
                pausetags = r2.hget("gridpausetags", strategyId)
                if pausetags != "2":  # 如果之前标记不为2，则发送短信提示，并将状态改为2
                    # res = requests.get(sendmessage_url, params={"userUuid": userUuid, "apiAccountId": apiAccountId,"strategyName": "量化", "runType": ""})
                    r2.hset("gridpausetags", strategyId, 2)
            else:
                # 获取网格交易卖单和买单列表
                sellnum = 0
                buynum = 0
                grid_sell_order = json.loads(r2.get("grid:sell:" + str(strategyId) + ":0"))
                print("网格{}卖单".format(strategyId), grid_sell_order)
                grid_buy_order = json.loads(r2.get("grid:buy:" + str(strategyId) + ":1"))
                print("网格{}买单".format(strategyId), grid_buy_order)
                sellnum = sellorderquery(grid_sell_order)
                if sellnum != count:
                    buynum = buyorderquery(grid_buy_order)
                elif sellnum == count:
                    conn = POOL_grid.connection()
                    cur = conn.cursor()
                    try:
                        finishsellprice = grid_orders["sellprice"]  # 已经成交单的价格
                        info2 = "量化策略{}已成交一个卖单，交易平台{}，成交价{}，成交数量{}，正在为您部署新的网格...".format(strategyId, platform,
                                                                                         finishsellprice, sellnum)
                        print(info2)
                        # logger.info(info2)
                        # 1、改变卖单状态
                        selltradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                        cur.execute(
                            'update t_gridtrade set sellstatus=%s,selltradetime=%s where strategyId=%s and sellorderid=%s',
                            (1, selltradetime, strategyId, grid_orders["sellorderid"]))
                        # 2、撤销买单grid_orders["buyorderid"]
                        cancerbuyorder(grid_orders, cur)
                        # 3、新挂一个卖单（比成交的卖单大一个网格，此时要注意余额是否足够)
                        selldata, buydata = restingneworder(finishsellprice, cur, grid_orders)
                        key_sell1 = "grid:sell:" + str(strategyId) + ":1"
                        key_buy1 = "grid:buy:" + str(strategyId) + ":1"
                        r2.set(key_sell1, json.dumps(selldata))
                        r2.set(key_buy1, json.dumps(buydata))
                        key = "grid:init:" + str(strategyId)
                        r2.set(key, json.dumps({}))  # 存入redis数据库
                    except Exception as e:
                        i = "用户{}网格策略{}平台{}密度卖单成交进行下一步操作时出错{}".format(userUuid, strategyId, platform, e)
                        print(i)
                        logger.error(i)
                    finally:
                        conn.commit()
                        cur.close()
                        conn.close()
                        # 调回状态
                elif buynum == count:
                    try:
                        conn = POOL_grid.connection()
                        cur = conn.cursor()
                        finishbuyprice = grid_orders["buyprice"]
                        info3 = "量化策略{}已成交一个买单，交易平台{}，成交价{}，成交数量{}，正在为您部署新的网格...".format(strategyId, platform,
                                                                                         finishbuyprice, buynum)
                        # r.lpush("gridinfo:{}".format(userId), info3)  # 信息存储到redis
                        # logger.info(info3)
                        print(info3)
                        buytradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                        # 1.撤销卖单
                        cancersellorder(grid_orders, cur)
                        # 2、新挂一个卖单,比最新成交价大一个网格区间
                        selldata0, buydata0 = restingneworder(finishbuyprice, cur, grid_orders)
                        key_sell0 = "grid:sell:" + str(strategyId) + ":0"
                        key_buy0 = "grid:buy:" + str(strategyId) + ":0"
                        key_sell1 = "grid:sell:" + str(strategyId) + ":1"
                        key_buy1 = "grid:buy:" + str(strategyId) + ":1"
                        selldata1 = r2.get(key_sell0)  # 交换位置
                        buydata1 = r2.get(key_buy0)
                        r2.set(key_sell0, json.dumps(selldata0))
                        r2.set(key_buy0, json.dumps(buydata0))
                        r2.set(key_sell1, selldata1)
                        r2.set(key_buy1, buydata1)
                    except Exception as e:
                        i = "用户{}网格策略{}平台{}密度买单成交进行下一步操作时出错{}".format(userUuid, strategyId, platform, e)
                        print(i)
                        logger.error(i)
                    finally:
                        conn.commit()
                        cur.close()
                        conn.close()
                        # 调回状态

    elif strategyType == 2:
        currentprice = \
            [i["currentprice"] for i in currentpricelist if i["platform"] == platform and i["symbol"] == symbol][0]
        info = "量化策略{}正在执行中...".format(strategyId)
        print(info)
        if currentprice == 0:  # 如果当前价为0，则取其他平台均价，如果其他平台也为0，则再取单个平台当前价
            currentpricelistnew = [i["currentprice"] for i in currentpricelist if
                                   i["symbol"] == symbol and i["currentprice"] != 0]
            if len(currentpricelistnew) != 0:
                currentprice = round(sum(currentpricelistnew) / len(currentpricelistnew),
                                     pricelimit[symbol][platform])
            else:
                currentprice = get_currentprice1(platform, symbol)
        print("{}平台{}交易对当前价格：{}".format(platform, symbol, currentprice))

        # 一、如果当前价小于等于止损价，止损出场
        if currentprice != 0 and currentprice <= lowprice + gap:  # 防止继续下单导致资金不足
            info1 = "行情到达止损价，暂停量化策略{}，您可以选择手动停止该策略，或者等待行情回调至网格区间继续运行。".format(strategyId)
            print(info1)
            # pausetags = r2.hget("gridpausetags", strategyId)
            # if pausetags != "1":  # 如果之前标记不为1，则发送短信提示，并将状态改为1
            #     # res = requests.get(sendmessage_url, params={"userUuid": userUuid, "apiAccountId": apiAccountId, "strategyName": "量化", "runType": ""})
            #     r2.hset("gridpausetags", strategyId, 1)
        # elif currentprice >= highprice - gap:  # 防止继续下单导致资金不足
        #     info2 = "行情上涨，已超出您的资金范围，暂停量化策略{}，您可以选择手动停止该策略，或者等待行情回调至网格区间继续运行。".format(strategyId)
        #     print(info2)
        else:
            # 获取网格交易卖单和买单列表
            sellnum = 0
            buynum = 0
            grid_sell_order = json.loads(r2.get("grid2:sell:" + str(strategyId)))
            print("网格{}卖单".format(strategyId), grid_sell_order)
            grid_buy_order = json.loads(r2.get("grid2:buy:" + str(strategyId)))
            print("网格{}买单".format(strategyId), grid_buy_order)
            sellnum = sellorderquery(grid_sell_order)
            sellnum = sellorderquery(grid_sell_order)
            if sellnum != count:
                buynum = buyorderquery(grid_buy_order)
            elif sellnum == count:
                conn = POOL_grid.connection()
                cur = conn.cursor()
                try:
                    finishsellprice = grid_sell_order["sellprice"]  # 已经成交单的价格
                    info2 = "量化策略{}已成交一个卖单，交易平台{}，成交价{}，成交数量{}，正在为您部署新的网格...".format(strategyId, platform,
                                                                                     finishsellprice, sellnum)
                    print(info2)
                    # logger.info(info2)
                    # 1、改变卖单状态
                    selltradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    cur.execute(
                        'update t_gridtrade set sellstatus=%s,selltradetime=%s where strategyId=%s and sellorderid=%s',
                        (1, selltradetime, strategyId, grid_sell_order["sellorderid"]))
                    # 2、撤销买单grid_orders["buyorderid"]
                    cancelbuyordrinfo = json.loads(r2.get("grid2:buy:" + str(strategyId)))
                    cancerbuyorder(cancelbuyordrinfo, cur)
                    # 3、新挂一个卖单（比成交的卖单大一个网格，此时要注意余额是否足够)
                    selldata, buydata = restingneworder(finishsellprice, cur, grid_sell_order)
                    key_sell = "grid2:sell:" + str(strategyId)
                    key_buy = "grid2:buy:" + str(strategyId)
                    r2.set(key_sell, json.dumps(selldata))
                    r2.set(key_buy, json.dumps(buydata))
                except Exception as e:
                    i = "用户{}网格策略{}平台{}密度卖单成交进行下一步操作时出错{}".format(userUuid, strategyId, platform, e)
                    print(i)
                    logger.error(i)
                finally:
                    conn.commit()
                    cur.close()
                    conn.close()
                    # 调回状态
            elif buynum == count:
                try:
                    conn = POOL_grid.connection()
                    cur = conn.cursor()
                    finishbuyprice = grid_buy_order["buyprice"]
                    info3 = "量化策略{}已成交一个买单，交易平台{}，成交价{}，成交数量{}，正在为您部署新的网格...".format(strategyId, platform,
                                                                                     finishbuyprice, buynum)
                    # r.lpush("gridinfo:{}".format(userId), info3)  # 信息存储到redis
                    # logger.info(info3)
                    print(info3)
                    buytradetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                    # 1.撤销卖单
                    cancelsellorderinfo = json.loads(r2.get("grid2:sell:" + str(strategyId)))
                    cancersellorder(cancelsellorderinfo, cur)
                    # 2、新挂一个卖单,比最新成交价大一个网格区间
                    selldata, buydata = restingneworder(finishbuyprice, cur, grid_buy_order)
                    key_sell = "grid2:sell:" + str(strategyId)
                    key_buy = "grid2:buy:" + str(strategyId)
                    r2.set(key_sell, json.dumps(selldata))
                    r2.set(key_buy, json.dumps(buydata))
                except Exception as e:
                    i = "用户{}网格策略{}平台{}密度买单成交进行下一步操作时出错{}".format(userUuid, strategyId, platform, e)
                    print(i)
                    logger.error(i)
                finally:
                    conn.commit()
                    cur.close()
                    conn.close()
                    # 调回状态


def goDoGridStrategy():
    gridnum = 8
    while True:
        try:
            print("*************************************************************")
            print("网格策略第{}次运行".format(gridnum))
            print("*************************************************************")
            currentpricelist = get_all_currentprice()  # 获取所有平台所有交易对最新价
            allgridstrategyId = r2.hkeys("gridstrategy")
            strategyIdlist = []
            for strategyId in allgridstrategyId:
                if strategyId[-1] == str(gridnum):
                    strategyIdlist.append(strategyId)
            if strategyIdlist == []:
                i = "没有符合条件的策略"
                print(i)
                time.sleep(1)
            else:
                gridThreads = []
                gridstrategydatalist = r2.hmget("gridstrategy", strategyIdlist)
                for griddata in gridstrategydatalist:
                    gridThreads.append(Thread(target=grid_strategy, args=(json.loads(griddata), currentpricelist)))
                for t in gridThreads:
                    t.start()
                for t in gridThreads:
                    t.join()
                del gridThreads
            del currentpricelist
            del allgridstrategyId
            del strategyIdlist
        except Exception as e:
            info = "网格多线程报错{}".format(e)
            print(info)
            logger.error(info)
        finally:
            time.sleep(1)
            gridnum += 1
            if gridnum == 10:
                gridnum = 0


if __name__ == '__main__':
    goDoGridStrategy()
