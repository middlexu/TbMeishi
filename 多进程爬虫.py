#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
import time

import os
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains, DesiredCapabilities
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pyquery import PyQuery as pq
from config import *
from multiprocessing import Pool, Process, Manager
import pymongo

# 多进程中，每个进程中所有数据（包括全局变量）都各有拥有一份，互不影响
# 解决方法，通过Manager()

# 实现了按顺序保存数据

ts = time.time()

client = pymongo.MongoClient(MONGO_URL)
db = client[MONGO_DB]

dcap = dict(DesiredCapabilities.PHANTOMJS)  # 设置useragent
# 根据需要设置具体的浏览器信息
dcap['phantomjs.page.settings.userAgent'] = (
    'Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.140 Safari/537.36')

# driver = webdriver.PhantomJS(desired_capabilities=dcap, service_args=SERVICE_ARGS)  # 封装浏览器信息
# driver = webdriver.PhantomJS(service_args=SERVICE_ARGS)
driver = webdriver.Chrome()
# browser.maximize_window()
wait = WebDriverWait(driver, 20)
# driver.set_window_size(1400, 900)


def search():
    try:
        driver.get("https://www.taobao.com")
        input_box = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#q")))
        submit = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR,
                                                        "#J_TSearchForm > div.search-button > button")))
        input_box.send_keys(KEY_WORDS)
        submit.click()
        total = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
                                                           "#mainsrp-pager > div > div > div > div.total")))
        # get_products(1)
        return total.text
    except TimeoutException:
        return search()


def goto_page(result, page_num):
    # all_tabs_former = driver.window_handles
    # try to open a new tab
    if not driver.current_url.startswith("https://s.taobao.com/"):
        # 打开新标签页
        # js = 'window.open("about:blank")'
        # driver.execute_script(js)
        # driver.switch_to.window(driver.window_handles[-1])

        search()

    try:
        input_box = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#mainsrp-pager > div > div > div > div.form > input")))
        submit = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR,
                                                            "#mainsrp-pager > div > div > div > div.form > span.btn.J_Submit")))
        input_box.clear()
        input_box.send_keys(page_num)
        submit.click()
        wait.until(EC.text_to_be_present_in_element((By.CSS_SELECTOR,
                                                     "#mainsrp-pager > div > div > div > ul > li.item.active > span"), str(page_num)))

        get_products(result, page_num)
        # driver.switch_to.window(driver.window_handles[0])
    except TimeoutException:
        goto_page(result, page_num)


def get_products(result, page_num):
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#mainsrp-itemlist .m-itemlist .items .item")))

    load_whole_page()

    html = driver.page_source
    doc = pq(html)
    items = doc("#mainsrp-itemlist .items .item").items()
    # i = 1
    temp_result = []
    for item in items:
        products = {
            "image": item.find(".pic .img").attr("src"),
            "price": item.find(".price").text(),
            "deal": item.find(".deal-cnt").text()[:-3],
            "title": item.find(".title").text(),
            "shop": item.find(".shop").text(),
            "location": item.find(".location").text()
        }
        # print("第" + str(page_num) + "页", end="")
        # print("第" + str(i) + "条数据", end="")
        # save_to_mongo(products)
        temp_result.append(products)
        # i += 1
    result[page_num] = temp_result


def load_whole_page():
    # 有时候中间一部分图片没有加载出来，需要在中间停顿一下
    # TODO: 感觉这一段比较乱
    html = driver.page_source
    doc = pq(html)
    product_one_page = len(doc("#mainsrp-itemlist .items .item"))
    # print(product_one_page)

    # 让界面（图片）缓存一下
    # 移动到商品一半的位置
    # 将页面定位到要查看的元素位置从而变相的实现了滚动条滚动的效果
    ac = driver.find_element_by_css_selector("#mainsrp-itemlist > div > div > div:nth-child(1) > div:nth-child(" +
                                             str(product_one_page // 2) + ")")
    ActionChains(driver).move_to_element(ac).perform()  # 定位鼠标到指定元素
    time.sleep(1)
    # 移动到最底端
    js = "var q=document.documentElement.scrollTop=10000"
    driver.execute_script(js)
    time.sleep(1)
    # 移动到商品2/3位置处
    ac = driver.find_element_by_css_selector("#mainsrp-itemlist > div > div > div:nth-child(1) > div:nth-child(" +
                                             str(product_one_page * 2 // 3) + ")")
    ActionChains(driver).move_to_element(ac).perform()  # 定位鼠标到指定元素
    time.sleep(1)

    try:
        # 移动到商品4/5位置处
        # （有时候执行这段代码错误：找不到这个元素。但是最终结果没有错。
        # 怀疑是try执行花了部分时间，执行的时候页面没加载全，执行后页面加载完全了）
        ac = driver.find_element_by_css_selector("#mainsrp-itemlist > div > div > div:nth-child(1) > div:nth-child(" +
                                                 str(product_one_page * 4 // 5) + ")")
        ActionChains(driver).move_to_element(ac).perform()  # 定位鼠标到指定元素
        time.sleep(1)
    except Exception:
        pass


def save_to_mongo(result, total):
    driver.quit()  # 关闭该进程浏览器
    i = 1
    while True:
        if i in result:  # 第i页的数据
            temp_result = result.pop(i)
            for j in range(len(temp_result)):
                try:
                    if db[MONGO_TABLE].insert(temp_result[j]):
                        print("第{}页第{}个商品数据存储到MONGODB成功".format(i, j+1), end="")
                        print(temp_result[j])
                except Exception:
                    print("第{}页第{}个商品数据存储到MONGODB失败".format(i, j+1), end="")
                    print(temp_result[j])
            i += 1
        if i > total:
            break
    # return i


def main():
    try:
        total = search()
        # get_products(1)
        total = int(re.compile("(\d+)").search(total).group(1))
        # total = 20
        driver.close()  # 关闭当前标签页
        driver.quit()  # 关闭浏览器全部标签页

        # # 启动储存进程
        # p = Process(target=save_to_mongo, args=(total, ))
        # p.start()

        result = Manager().dict()

        # 启动多进程
        pool = Pool(4)
        # 用map和apply_async都可以，似乎是没有区别的
        # pool.map(goto_page, list(range(1, total + 1)))
        # 不知道为什么开启多进程还有一个浏览器关不掉
        pool.apply_async(save_to_mongo, args=(result, total))
        # time.sleep(10)
        # pool.apply_async(save_to_mongo, args=(total,))
        for i in range(1, total + 1):
            pool.apply_async(goto_page, args=(result, i))
            # time.sleep(15)

        # 注意: 进程里的浏览器不会关闭
        pool.close()  # 对Pool对象调用join()方法会等待所有子进程执行完毕，调用join()之前必须先调用close()，调用close()之后就不能继续添加新的Process了。
        pool.join()

    except Exception:
        print("出错了！")

    print("多进程Took {}s".format(time.time() - ts))
    # 强制关闭进程
    os.system('taskkill /f /im chromedriver.exe')
    os.system('taskkill /f /im chrome.exe')
    # os.system('taskkill /f /im phantomjs.exe')


if __name__ == "__main__":
    main()


# 下面是演示无界面操作
# from pyvirtualdisplay import Display
# from selenium import webdriver
#
# display = Display(visible=0, size=(800, 600))
# display.start()
#
# # now Firefox will run in a virtual display.
# # you will not see the browser.
# browser = webdriver.Chrome()
# browser.get('http://www.baidu.com')
# print browser.title
# browser.quit()
#
# display.stop()