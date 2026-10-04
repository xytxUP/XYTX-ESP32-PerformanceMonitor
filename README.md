# XYTX-ESP32-PerformanceMonitor
基于esp32c3的性能监视器，基于lvgl，可以用折线图显示电脑的资源占用，详细信息见我的B站：
https://space.bilibili.com/3493086827120707
本人是个刚升初一的学生党，真的不懂这些，代码是大肥鱼写的（
神秘数字：3883262703
<img width="418" height="813" alt="image" src="https://github.com/user-attachments/assets/175f7275-214c-4ae5-ad0d-8e8f39d33cb7" />
<img width="662" height="884" alt="image" src="https://github.com/user-attachments/assets/f1a7584d-8044-42e7-95fb-a337ccc93a0b" />
<img width="661" height="881" alt="image" src="https://github.com/user-attachments/assets/9795f904-a01b-4b31-aeac-5807c9283824" />
测试用的是合宙esp32c3，128x160 st7735屏幕，拼夕夕很便宜就能买到
开发板尽量买带串口芯片的，不然需要外接串口模块喵
接线表：
开发板	屏幕
GND	VDD
3.3V	VDD
IO06	SCL
IO07	SDA
IO10	RST
IO05	DC
IO04	CS
IO03	BLK
<img width="145" height="172" alt="image" src="https://github.com/user-attachments/assets/f9aff1f1-5a0b-42eb-8259-7e3e0dc8f559" />

请大家不要接错，不然板子可能会坏掉的!

食用方法喵：
1.安装Arduino IDE 2和python，微软商店直接搜
2.打开arduinoide，等他加载亿会，进来之后点文件-首选项，把这一堆玩意粘贴到其他开发版管理器地址里面，点确定
<img width="772" height="33" alt="image" src="https://github.com/user-attachments/assets/86bd6f69-d52f-4712-b968-71d4459643be" />
https://dl.espressif.com/dl/package_esp32_index.json
https://github.com/Bodmer/TFT_eSPI
3.在左边那一栏找到开发板管理器，搜esp32，把这两个玩意都装上，安装可能很慢，多等一会
<img width="265" height="766" alt="image" src="https://github.com/user-attachments/assets/23eae822-9081-4d3b-bb38-2a8145ce1237" />
4.在左边的库管理，搜tft_espi，lvgl，arduinojson，把他们全装上，注意lvgl要装8.4.0
<img width="266" height="404" alt="image" src="https://github.com/user-attachments/assets/b024ef46-0abc-4436-9f45-5b1ae656c24a" />
<img width="214" height="209" alt="image" src="https://github.com/user-attachments/assets/0344a377-9295-432e-b9e3-0cb550fe0aec" />
<img width="208" height="213" alt="image" src="https://github.com/user-attachments/assets/7a1227d3-215c-4ac4-86cd-b60980abbbea" />
5.装好后打开此电脑，打开文档\Arduino\libraries\TFT_eSPI,把我提供的配置里面的User_Setup.h替换进来，如果要改线序或用其他屏幕就改这个文件，再返回libraries文件夹，打开lvgl，再把我提供的配置里面的lv_conf.h替换进来
<img width="1279" height="1023" alt="image" src="https://github.com/user-attachments/assets/1ab309ca-7dfb-496d-9857-38a62663ea7b" />
6，双击arduino\arduino.ino，打开arduinoide，插上你的开发板，左上角选择开发板，如果你不知道你的开发板是com几，就重新插一次选多出的那个
<img width="1279" height="1023" alt="image" src="https://github.com/user-attachments/assets/ff17d8c3-1d5a-439e-ad37-395eb2e13f8f" />
<img width="500" height="504" alt="image" src="https://github.com/user-attachments/assets/4cad2092-562b-4d92-92cf-80c790e2692f" />
7.之后会来到这个界面，左侧搜esp32c3
<img width="698" height="516" alt="image" src="https://github.com/user-attachments/assets/9f85d1ee-a084-4765-87d4-107258a589b8" />
选这个ESP32C3 Dev Module
8.点左上角的工具，把这里的QIO改成DIO，不改的话板子无法正常工作
<img width="815" height="834" alt="image" src="https://github.com/user-attachments/assets/711bed9e-bc1c-4e67-8fcb-4792625f30c3" />
9.点左上角的这个箭头上传，等他编译亿会
<img width="53" height="46" alt="image" src="https://github.com/user-attachments/assets/73b2bc6d-b0a2-4afa-a408-813a1173ce71" />
<img width="1279" height="1023" alt="image" src="https://github.com/user-attachments/assets/31a9e47d-2474-4794-b42c-eadf23efa93e" />
如果没有报错的话就成功了，如果报错的话...检查前面做对了吗
<img width="1279" height="1023" alt="image" src="https://github.com/user-attachments/assets/0dadc84a-cfce-4291-8151-47aba561fbfc" />
到了这个界面就恭喜你成功了喵
保持开发板连接电脑
10.打开python\main.pyw,第一次打开时间会比较长不要重复打开
来到这个界面就说明程序正常运行了
<img width="416" height="804" alt="image" src="https://github.com/user-attachments/assets/48464f94-f53d-43a9-9123-85820ce45218" />
不要删除settings.json，不然会丢失个性化设置
如果gpu占用显示错误就取消勾选显示gpu图表
可以添加自启动让它开机自动运行
如果有问题，B站私信我，都是会回复的！
欢迎大家提出意见！
