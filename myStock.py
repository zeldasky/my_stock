import datetime as dt
import FinanceDataReader as fdr

stock_list = [['hynix',65,131677],
                ['samsung',150,71326],
                ['apple',110,185],
                ['amd',32,183],
                ['google',100,138],
                ['ms',56,326]]

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
    samsung_price = int(df_samsung['Close'].values[0])
    df_hynix = fdr.DataReader(get_korea_stock_code("SK하이닉스"), yesterday, current)
    hynix_price = int(df_hynix['Close'].values[0])

    df_apple = fdr.DataReader('AAPL', yesterday, current)
    apple_price = int(df_apple['Close'].values[0])
    df_ms = fdr.DataReader('MSFT', yesterday, current)
    ms_price = int(df_ms['Close'].values[0])
    df_google = fdr.DataReader('GOOGL', yesterday, current)
    google_price = int(df_google['Close'].values[0])
    df_amd = fdr.DataReader('AMD', yesterday, current)
    amd_price = int(df_amd['Close'].values[0])

    price_list = {'hynix':hynix_price, 'samsung':samsung_price, 'apple':apple_price,
                  'amd':amd_price, 'ms':ms_price, 'google':google_price}

    # print(hynix_price)
    # print(samsung_price)
    # print(apple_price)
    # print(amd_price)
    # print(ms_price)
    # print(google_price)
    for i in stock_list:
        rate = 1
        if i[0] != 'samsung' and i[0] != 'hynix':
            rate = exchange_rate
        first_total += i[2]*i[1]*rate
        current_total += price_list[i[0]]*i[1]*rate
    return first_total, current_total

if __name__ == '__main__':
    seed, total = get_buget()
    print("\n---------------------------------------------")
    print("------- 상규 & 인영 주식 투자 내역 ----------")
    # print("---------------------------------------------")
    # print("하이닉스 : ")
    # print("{0:>30,} 원".format(total))
    # print("삼성: ")
    # print("{0:>30,} 원".format(total))
    # print("애플: ")
    # print("{0:>30,} 원".format(total))
    # print("AMD: ")
    # print("{0:>30,} 원".format(total))
    # print("MS: ")
    # print("{0:>30,} 원".format(total))
    # print("Google: ")
    # print("{0:>30,} 원".format(total))
    print("---------------------------------------------")
    print("시드 : ")
    print("{0:>30,} 원".format(seed))
    print("평가액 : ")
    print("{0:>30,} 원".format(total))
    print("수익율 : ")
    print("{0:>30,} %".format(round((total - seed)/seed*100)))
    print("---------------------------------------------\n")
    