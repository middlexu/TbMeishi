#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
import threading
import time
from queue import Queue
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains, DesiredCapabilities
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pyquery import PyQuery as pq
from config import *
import pymongo


# 处理失败，多线程被杀死，只留下一个线程
# 应该是selenium不适合多线程

ts = time.time()

SHARE_Q = Queue()  # 构造一个不限制大小的的队列
_WORKER_THREAD_NUM = 3  # 设置线程的个数
exitFlag = 0
queueLock = threading.Lock()

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
        get_products(1)
        return total.text
    except TimeoutException:
        return search()


def goto_page(page_num):
    if not driver.current_url.startswith("https://s.taobao.com/"):
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

        get_products(page_num)
    except TimeoutException:
        goto_page(page_num)


def get_products(page_num):
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#mainsrp-itemlist .m-itemlist .items .item")))

    load_whole_page()

    html = driver.page_source
    doc = pq(html)
    items = doc("#mainsrp-itemlist .items .item").items()
    i = 1
    for item in items:
        products = {
            "image": item.find(".pic .img").attr("src"),
            "price": item.find(".price").text(),
            "deal": item.find(".deal-cnt").text()[:-3],
            "title": item.find(".title").text(),
            "shop": item.find(".shop").text(),
            "location": item.find(".location").text()
        }
        print("第" + str(page_num) + "页", end="")
        print("第" + str(i) + "条数据", end="")
        save_to_mongo(products)
        i += 1


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


def save_to_mongo(result):
    try:
        if db[MONGO_TABLE].insert(result):
            print("存储到MONGODB成功", result)
    except Exception:
        print("存储到MONGODB失败", result)


class MyThread(threading.Thread):
    def __init__(self, func):
        super().__init__()
        self.func = func

    def run(self):  # 把要执行的代码写到run函数里面 线程在创建后会直接运行run函数
        # 重写基类的run方法
        self.func()


def worker():
    """
    主要用来写工作逻辑, 只要队列不空持续处理
    队列为空时, 检查队列, 由于Queue中已经包含了wait,
    notify和锁, 所以不需要在取任务或者放任务的时候加锁解锁
    上面这段话没太懂
    """
    global SHARE_Q
    while not exitFlag:
        queueLock.acquire()
        if not SHARE_Q.empty():
            page_num = SHARE_Q.get()  # 获得任务
            queueLock.release()
            # do_something(item)
            goto_page(page_num)
            time.sleep(1)
            SHARE_Q.task_done()
            # Queue.task_done() 在完成一项工作之后，Queue.task_done()函数向任务已经完成的队列发送一个信号
            # 暂时不知道这句SHARE_Q.task_done()有什么用
        else:
            queueLock.release()


def main():
    try:
        total = search()
        total = int(re.compile("(\d+)").search(total).group(1))

        # 这段是单线程
        # for i in range(2, total+1):
        #     #print("第" + str(i) + "页")
        #     next_page(i)

        threads = []

        # 开启_WORKER_THREAD_NUM(上文为3)个新线程
        for i in range(_WORKER_THREAD_NUM):
            thread = MyThread(worker)
            thread.setDaemon(True)
            thread.start()  # 线程开始处理任务
            threads.append(thread)

        # 向队列中放入任务,填充队列
        queueLock.acquire()
        for task in range(2, total):
            SHARE_Q.put(task)
        queueLock.release()

        # 等待队列清空
        while not SHARE_Q.empty():
            pass

        # 通知线程是时候退出
        exitFlag = 1

        # 等待所有线程完成
        for thread in threads:
            thread.join()
        SHARE_Q.join()

    except Exception:
        print("出错了！")
    finally:
        driver.close()  # 关闭当前标签页
    driver.quit()  # 关闭浏览器全部标签页
    print("Took {}s".format(time.time() - ts))


if __name__ == "__main__":
    main()
