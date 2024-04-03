import datetime as dt
import FinanceDataReader as fdr

en_name = 0
stock_quantity = 1
initial_price = 2
kr_name = 3
current_price = 4
profit_rate = 5
exchange_rate = 6
display_rate = 7

#en_name, stock_quantity, initial_price, kr_name, current_price, profit_rate, exchange_rate, display_rate
stock_list = [['hynix',65,131677,'하이닉스', 0, 0, 1, '원'],
                ['samsung',150,71326, '삼성전자', 0, 0, 1, '원'],
                ['apple',110,185, '애플', 0, 0, 1, '달러'],
                ['amd',32,183, 'AMD', 0, 0, 1, '달러'],
                ['google',100,138, '구글', 0, 0, 1, '달러'],
                ['ms',56,326, '마이크로소프트', 0, 0, 1, '달러']]

def get_korea_stock_code(name):
    df_list = fdr.StockListing('KRX')
    df_filter = df_list.loc[df_list['Name']==name]
    code = df_filter['Code'].values[0]
    return code

def get_profit_range(initial,current):
    return int((current - initial)/initial*100)
    
def get_stock_profit():
    first_total = 0
    current_total = 0
    current =  dt.datetime.now()
    yesterday = current - dt.timedelta(days=2) 
    current_exchange_rate = int(fdr.DataReader('USD/KRW').iloc[-1]['Close'])

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

    for stock in stock_list:
        stock[current_price] = price_list[stock[en_name]]
        stock[profit_rate] = get_profit_range(stock[initial_price], stock[current_price])
        if stock[en_name] != 'samsung' and stock[en_name] != 'hynix':
            stock[exchange_rate] = current_exchange_rate
        weight = stock[stock_quantity] * stock[initial_price] * stock[exchange_rate]
        # 상세 투자 내역 확인이 필요하면 아래 주석 삭제
        # print(stock[kr_name] + "(투자금액 : " + "{0:,}원".format(weight) + ")")
        # print("--> 현재가격 : " + "{0:,}".format(stock[current_price]) + stock[display_rate] + " ,매수가격: " + "{0:,}".format(stock[initial_price]) + stock[display_rate])
        # print("--> 수익률: " + str(stock[profit_rate]) + "% -> " + "{0:,}".format(int(weight*stock[profit_rate]/100)) + "원\n")
        first_total += stock[initial_price] * stock[stock_quantity] * stock[exchange_rate]
        current_total += stock[current_price] * stock[stock_quantity] * stock[exchange_rate]

    return first_total, current_total

if __name__ == '__main__':
    seed, total = get_stock_profit()
    print("\n---------------------------------------------")
    print("-------- 상규 & 인영 주식 투자 내역 ---------")
    print("---------------------------------------------\n")
    print("시드 : ")
    print("{0:>20,} 원".format(seed))
    print("평가액 : ")
    print("{0:>20,} 원".format(total))
    print("수익율 : ")
    print("{0:>20,} 원".format(total - seed) + "({0:>3,} %)".format(get_profit_range(seed, total)))
    print("\n---------------------------------------------\n")
    