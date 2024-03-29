import datetime as dt
import FinanceDataReader as fdr

stock_list = [['hynix',65,131677,'하이닉스'],
                ['samsung',150,71326, '삼성전자'],
                ['apple',110,185, '애플'],
                ['amd',32,183, 'AMD'],
                ['google',100,138, '구글'],
                ['ms',56,326, '마이크로소프트']]

def get_korea_stock_code(name):
    df_list = fdr.StockListing('KRX')
    df_filter = df_list.loc[df_list['Name']==name]
    code = df_filter['Code'].values[0]
    return code

def get_buget():
    first_total = 0
    current_total = 0
    current =  dt.datetime.now()
    yesterday = current - dt.timedelta(days=2) 
    exchange_rate = int(fdr.DataReader('USD/KRW').iloc[-1]['Close'])

    df_samsung = fdr.DataReader(get_korea_stock_code("삼성전자"), yesterday, current)
    samsung_price = int(df_samsung['Close'].values[-1])
    df_hynix = fdr.DataReader(get_korea_stock_code("SK하이닉스"), yesterday, current)
    hynix_price = int(df_hynix['Close'].values[-1])

    df_apple = fdr.DataReader('AAPL', yesterday, current)
    apple_price = int(df_apple['Close'].values[-1])
    df_ms = fdr.DataReader('MSFT', yesterday, current)
    ms_price = int(df_ms['Close'].values[-1])
    df_google = fdr.DataReader('GOOGL', yesterday, current)
    google_price = int(df_google['Close'].values[-1])
    df_amd = fdr.DataReader('AMD', yesterday, current)
    amd_price = int(df_amd['Close'].values[-1])

    price_list = {'hynix':hynix_price, 'samsung':samsung_price, 'apple':apple_price,
                  'amd':amd_price, 'ms':ms_price, 'google':google_price}

    print("-----------------------------------------------------------------\n")
    for data in stock_list:
        if data[0] != 'samsung' and data[0] != 'hynix':
            print(data[3] + ": ")
            print("(비중: " + "{0:,}원".format(data[1]*data[2]*exchange_rate) + ")")
            print("{0:>30,}달러".format(price_list[data[0]]) + " (매수가격" + "{0:,}달러".format(data[2]) + ", 수익률: " + str(round((price_list[data[0]]- data[2])/data[2]*100,2)) + "%)")
        else:
            print(data[3] + ": ")
            print("(비중: " + "{0:,}원".format(data[1]*data[2]) + ")")
            print("{0:>30,}원".format(price_list[data[0]]) + " (매수가격" + "{0:,}원".format(data[2]) + ", 수익률: " + str(round((price_list[data[0]]- data[2])/data[2]*100,2)) + "%)")

    for i in stock_list:
        rate = 1
        if i[0] != 'samsung' and i[0] != 'hynix':
            rate = exchange_rate
        first_total += i[2]*i[1]*rate
        current_total += price_list[i[0]]*i[1]*rate
    return first_total, current_total

if __name__ == '__main__':
    seed, total = get_buget()
    print("\n-----------------------------------------------------------------")
    print("-------------------- 상규 & 인영 주식 투자 내역 -----------------------")
    print("-----------------------------------------------------------------\n")
    print("시드 : ")
    print("{0:>30,} 원".format(seed))
    print("평가액 : ")
    print("{0:>30,} 원".format(total))
    print("수익율 : ")
    print("{0:>30,} 원".format(total - seed) + " ({0:>3,} %".format(round((total - seed)/seed*100, 2)) + ")")
    print("\n-----------------------------------------------------------------\n")
    