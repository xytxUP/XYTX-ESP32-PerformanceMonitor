#include <lvgl.h>
#include <TFT_eSPI.h>
#include <ArduinoJson.h>

// ============================================================
//  背光引脚
// ============================================================
#define PIN_BL          3
#define BL_TIMEOUT_MS   10000UL

// ============================================================
//  显示
// ============================================================
TFT_eSPI tft = TFT_eSPI();
static lv_disp_draw_buf_t draw_buf;
static lv_color_t buf[128 * 20];

// ============================================================
//  颜色
// ============================================================
lv_color_t c_bg, c_text, c_text_dim, c_grid, c_border;
lv_color_t c_cpu, c_mem, c_gpu, c_temp;

#define COL_WAIT  0xB8A04A

void setDefaultColors() {
    c_bg       = lv_color_hex(0xFFFFFF);
    c_text     = lv_color_hex(0x202020);
    c_text_dim = lv_color_hex(0x909090);
    c_grid     = lv_color_hex(0xE8E8E8);
    c_border   = lv_color_hex(0xD0D0D0);
    c_cpu      = lv_color_hex(0x1F77B4);
    c_mem      = lv_color_hex(0x2CA02C);
    c_gpu      = lv_color_hex(0xFF7F0E);
    c_temp     = lv_color_hex(0xD62728);
}

lv_color_t parseHex(const char *s, uint32_t def) {
    if (!s || !*s) return lv_color_hex(def);
    if (*s == '#') s++;
    uint32_t v = strtoul(s, NULL, 16);
    return lv_color_hex(v & 0xFFFFFF);
}

// 柱子颜色 = 折线颜色加深 10
lv_color_t shadeBar(lv_color_t c) {
    return lv_color_darken(c, 10);
}

// ============================================================
//  数据
// ============================================================
struct Data {
    float cpu = 0, mem = 0, gpu = 0, cpu_temp = 0;
    bool has_temp = false;
    bool gpu_ok = false;
    String cpu_name = "", gpu_name = "";
    bool has_data = false;
};
Data d;

// ============================================================
//  图表对象
// ============================================================
#define CPU_N 60
#define MEM_N 30
#define GPU_N 30

lv_obj_t *chartCPUArea;   lv_chart_series_t *serCPUArea;
lv_obj_t *chartCPU;       lv_chart_series_t *serCPU, *serCPUTemp;
lv_obj_t *chartMEMArea;   lv_chart_series_t *serMEMArea;
lv_obj_t *chartMEM;       lv_chart_series_t *serMEM;
lv_obj_t *chartGPUArea;   lv_chart_series_t *serGPUArea;
lv_obj_t *chartGPU;       lv_chart_series_t *serGPU;

lv_obj_t *topLabel;
lv_obj_t *tCPU, *tMEM, *tGPU;
lv_obj_t *vCPU, *vMEM, *vGPU;

lv_obj_t *waitScreen = NULL;
lv_obj_t *waitLabel  = NULL;

bool gpuShown = false;
String serialBuffer = "";

unsigned long lastSerialTime = 0;
bool backlightOn = true;
bool everReceived = false;

// ============================================================
//  LVGL flush
// ============================================================
void disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
    uint32_t w = (area->x2 - area->x1 + 1);
    uint32_t h = (area->y2 - area->y1 + 1);
    tft.startWrite();
    tft.setAddrWindow(area->x1, area->y1, w, h);
    tft.pushColors((uint16_t *)&color_p->full, w * h, true);
    tft.endWrite();
    lv_disp_flush_ready(disp);
}

// ============================================================
//  图表工厂
// ============================================================
lv_obj_t* createLineChart(lv_coord_t x, lv_coord_t y, lv_coord_t w, lv_coord_t h, int pts) {
    lv_obj_t *c = lv_chart_create(lv_scr_act());
    lv_obj_set_pos(c, x, y);
    lv_obj_set_size(c, w, h);
    lv_chart_set_type(c, LV_CHART_TYPE_LINE);
    lv_chart_set_range(c, LV_CHART_AXIS_PRIMARY_Y, 0, 100);
    lv_chart_set_point_count(c, pts);
    lv_chart_set_update_mode(c, LV_CHART_UPDATE_MODE_SHIFT);
    lv_chart_set_div_line_count(c, 0, 0);
    lv_obj_set_style_bg_opa(c, LV_OPA_TRANSP, 0);
    lv_obj_set_style_pad_all(c, 0, 0);
    lv_obj_set_style_size(c, 0, LV_PART_INDICATOR);
    lv_obj_set_style_line_width(c, 2, LV_PART_ITEMS);
    lv_obj_set_style_border_width(c, 1, 0);
    lv_obj_set_style_border_color(c, c_border, 0);
    lv_obj_set_style_border_opa(c, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(c, 2, 0);
    return c;
}

lv_obj_t* createBarFillChart(lv_coord_t x, lv_coord_t y, lv_coord_t w, lv_coord_t h, int pts) {
    lv_obj_t *c = lv_chart_create(lv_scr_act());
    lv_obj_set_pos(c, x, y);
    lv_obj_set_size(c, w, h);
    lv_chart_set_type(c, LV_CHART_TYPE_BAR);
    lv_chart_set_range(c, LV_CHART_AXIS_PRIMARY_Y, 0, 100);
    lv_chart_set_point_count(c, pts);
    lv_chart_set_update_mode(c, LV_CHART_UPDATE_MODE_SHIFT);   // 柱子随数据滚动
    lv_chart_set_div_line_count(c, 0, 0);
    lv_obj_set_style_bg_opa(c, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(c, 0, 0);
    lv_obj_set_style_pad_all(c, 0, 0);
    lv_obj_set_style_pad_column(c, 0, LV_PART_MAIN);
    lv_obj_set_style_bg_opa(c, LV_OPA_40, LV_PART_ITEMS);      // 半透明
    lv_obj_set_style_border_width(c, 0, LV_PART_ITEMS);
    return c;
}

// ============================================================
//  等待界面
// ============================================================
void showWaitScreen() {
    if (waitScreen) return;
    waitScreen = lv_obj_create(lv_scr_act());
    lv_obj_set_size(waitScreen, 128, 160);
    lv_obj_set_pos(waitScreen, 0, 0);
    lv_obj_set_style_radius(waitScreen, 0, 0);
    lv_obj_set_style_bg_color(waitScreen, lv_color_hex(COL_WAIT), 0);
    lv_obj_set_style_bg_opa(waitScreen, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(waitScreen, 0, 0);
    lv_obj_clear_flag(waitScreen, LV_OBJ_FLAG_SCROLLABLE);
    waitLabel = lv_label_create(waitScreen);
    lv_label_set_text(waitLabel, "WAITING...");
    lv_obj_set_style_text_color(waitLabel, lv_color_hex(0x4A3200), 0);
    lv_obj_set_style_text_font(waitLabel, &lv_font_montserrat_14, 0);
    lv_obj_center(waitLabel);
}

void hideWaitScreen() {
    if (waitScreen) {
        lv_obj_del(waitScreen);
        waitScreen = NULL;
        waitLabel  = NULL;
    }
}

// ============================================================
//  布局
// ============================================================
void applyLayout(bool showGpu) {
    lv_obj_set_pos(topLabel, 1, 0);
    lv_obj_set_size(topLabel, 126, 14);

    // CPU 全宽 (62px 高)
    lv_obj_set_pos(chartCPUArea, 1, 15);
    lv_obj_set_size(chartCPUArea, 126, 62);
    lv_obj_set_pos(chartCPU, 1, 15);
    lv_obj_set_size(chartCPU, 126, 62);
    lv_obj_set_pos(tCPU, 4, 15);       // 标题左上
    lv_obj_set_pos(vCPU, 68, 15);      // CPU 数值右上（因为有双线）

    if (showGpu) {
        // MEM 左 (62x78)
        lv_obj_set_pos(chartMEMArea, 1, 80);
        lv_obj_set_size(chartMEMArea, 62, 78);
        lv_obj_set_pos(chartMEM, 1, 80);
        lv_obj_set_size(chartMEM, 62, 78);
        // GPU 右 (62x78)
        lv_obj_set_pos(chartGPUArea, 65, 80);
        lv_obj_set_size(chartGPUArea, 62, 78);
        lv_obj_set_pos(chartGPU, 65, 80);
        lv_obj_set_size(chartGPU, 62, 78);

        // 标题左上
        lv_obj_set_pos(tMEM, 4, 80);
        lv_obj_set_pos(tGPU, 68, 80);

        // ★ 数值标签居中
        // MEM 图中心 ≈ (32, 119)，标签约 30x14 → 左上 (17, 112)
        lv_obj_set_pos(vMEM, 18, 112);
        // GPU 图中心 ≈ (96, 119) → 左上 (82, 112)
        lv_obj_set_pos(vGPU, 82, 112);

        lv_obj_clear_flag(chartGPUArea, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(chartGPU,     LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(tGPU,         LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(vGPU,         LV_OBJ_FLAG_HIDDEN);
    } else {
        // MEM 全宽
        lv_obj_set_pos(chartMEMArea, 1, 80);
        lv_obj_set_size(chartMEMArea, 126, 78);
        lv_obj_set_pos(chartMEM, 1, 80);
        lv_obj_set_size(chartMEM, 126, 78);

        lv_obj_set_pos(tMEM, 4, 80);
        // ★ 单图表模式：MEM 数值也居中
        lv_obj_set_pos(vMEM, 50, 112);

        lv_obj_add_flag(chartGPUArea, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(chartGPU,     LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(tGPU,         LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(vGPU,         LV_OBJ_FLAG_HIDDEN);
    }
    gpuShown = showGpu;
}

// ============================================================
//  应用颜色
// ============================================================
void applyColorsToUI() {
    lv_obj_set_style_bg_color(lv_scr_act(), c_bg, 0);
    lv_obj_set_style_bg_opa(lv_scr_act(), LV_OPA_COVER, 0);

    // 文字
    lv_obj_set_style_text_color(topLabel, c_text_dim, 0);
    lv_obj_set_style_text_color(tCPU, c_text, 0);
    lv_obj_set_style_text_color(tMEM, c_text, 0);
    lv_obj_set_style_text_color(tGPU, c_text, 0);
    lv_obj_set_style_text_color(vCPU, c_cpu, 0);      // CPU 保持品牌色
    // ★ MEM/GPU 数值颜色跟随文字（浅色黑 / 深色白）
    lv_obj_set_style_text_color(vMEM, c_text, 0);
    lv_obj_set_style_text_color(vGPU, c_text, 0);

    // 折线颜色
    lv_chart_set_series_color(chartCPU, serCPU, c_cpu);
    lv_chart_set_series_color(chartCPU, serCPUTemp, c_temp);
    lv_chart_set_series_color(chartMEM, serMEM, c_mem);
    lv_chart_set_series_color(chartGPU, serGPU, c_gpu);

    // ★ 柱子颜色 = 折线色加深 10
    lv_color_t c_cpu_bar = shadeBar(c_cpu);
    lv_color_t c_mem_bar = shadeBar(c_mem);
    lv_color_t c_gpu_bar = shadeBar(c_gpu);

    lv_chart_set_series_color(chartCPUArea, serCPUArea, c_cpu_bar);
    lv_obj_set_style_bg_color(chartCPUArea, c_cpu_bar, LV_PART_ITEMS);
    lv_obj_set_style_bg_opa(chartCPUArea, LV_OPA_40, LV_PART_ITEMS);

    lv_chart_set_series_color(chartMEMArea, serMEMArea, c_mem_bar);
    lv_obj_set_style_bg_color(chartMEMArea, c_mem_bar, LV_PART_ITEMS);
    lv_obj_set_style_bg_opa(chartMEMArea, LV_OPA_40, LV_PART_ITEMS);

    lv_chart_set_series_color(chartGPUArea, serGPUArea, c_gpu_bar);
    lv_obj_set_style_bg_color(chartGPUArea, c_gpu_bar, LV_PART_ITEMS);
    lv_obj_set_style_bg_opa(chartGPUArea, LV_OPA_40, LV_PART_ITEMS);

    // 边框
    lv_obj_set_style_border_color(chartCPU, c_border, 0);
    lv_obj_set_style_border_color(chartMEM, c_border, 0);
    lv_obj_set_style_border_color(chartGPU, c_border, 0);

    lv_obj_invalidate(lv_scr_act());
}

// ============================================================
//  构建 UI
// ============================================================
void buildUI() {
    topLabel = lv_label_create(lv_scr_act());
    lv_obj_set_style_text_font(topLabel, &lv_font_montserrat_14, 0);
    lv_label_set_long_mode(topLabel, LV_LABEL_LONG_SCROLL_CIRCULAR);
    lv_label_set_text(topLabel, "");
    lv_obj_add_flag(topLabel, LV_OBJ_FLAG_HIDDEN);

    // CPU 填充 + 折线
    chartCPUArea = createBarFillChart(1, 15, 126, 62, CPU_N);
    serCPUArea = lv_chart_add_series(chartCPUArea, c_cpu, LV_CHART_AXIS_PRIMARY_Y);
    chartCPU = createLineChart(1, 15, 126, 62, CPU_N);
    serCPU     = lv_chart_add_series(chartCPU, c_cpu,  LV_CHART_AXIS_PRIMARY_Y);
    serCPUTemp = lv_chart_add_series(chartCPU, c_temp, LV_CHART_AXIS_PRIMARY_Y);

    // MEM 填充 + 折线
    chartMEMArea = createBarFillChart(1, 80, 62, 78, MEM_N);
    serMEMArea = lv_chart_add_series(chartMEMArea, c_mem, LV_CHART_AXIS_PRIMARY_Y);
    chartMEM = createLineChart(1, 80, 62, 78, MEM_N);
    serMEM = lv_chart_add_series(chartMEM, c_mem, LV_CHART_AXIS_PRIMARY_Y);

    // GPU 填充 + 折线
    chartGPUArea = createBarFillChart(65, 80, 62, 78, GPU_N);
    serGPUArea = lv_chart_add_series(chartGPUArea, c_gpu, LV_CHART_AXIS_PRIMARY_Y);
    chartGPU = createLineChart(65, 80, 62, 78, GPU_N);
    serGPU = lv_chart_add_series(chartGPU, c_gpu, LV_CHART_AXIS_PRIMARY_Y);

    // 预填充
    for (int i = 0; i < CPU_N; i++) {
        lv_chart_set_next_value(chartCPUArea, serCPUArea, 0);
        lv_chart_set_next_value(chartCPU, serCPU, 0);
        lv_chart_set_next_value(chartCPU, serCPUTemp, 0);
    }
    for (int i = 0; i < MEM_N; i++) {
        lv_chart_set_next_value(chartMEMArea, serMEMArea, 0);
        lv_chart_set_next_value(chartMEM, serMEM, 0);
        lv_chart_set_next_value(chartGPUArea, serGPUArea, 0);
        lv_chart_set_next_value(chartGPU, serGPU, 0);
    }

    // 标题
    tCPU = lv_label_create(lv_scr_act()); lv_label_set_text(tCPU, "CPU");
    lv_obj_set_style_text_font(tCPU, &lv_font_montserrat_14, 0);
    tMEM = lv_label_create(lv_scr_act()); lv_label_set_text(tMEM, "MEM");
    lv_obj_set_style_text_font(tMEM, &lv_font_montserrat_14, 0);
    tGPU = lv_label_create(lv_scr_act()); lv_label_set_text(tGPU, "GPU");
    lv_obj_set_style_text_font(tGPU, &lv_font_montserrat_14, 0);

    // 数值
    vCPU = lv_label_create(lv_scr_act()); lv_label_set_text(vCPU, "--");
    lv_obj_set_style_text_font(vCPU, &lv_font_montserrat_14, 0);
    vMEM = lv_label_create(lv_scr_act()); lv_label_set_text(vMEM, "--");
    lv_obj_set_style_text_font(vMEM, &lv_font_montserrat_14, 0);
    vGPU = lv_label_create(lv_scr_act()); lv_label_set_text(vGPU, "--");
    lv_obj_set_style_text_font(vGPU, &lv_font_montserrat_14, 0);

    applyLayout(false);
    applyColorsToUI();
    showWaitScreen();
}

// ============================================================
//  数据更新
// ============================================================
void updateCharts() {
    lv_chart_set_next_value(chartCPUArea, serCPUArea, (lv_coord_t)d.cpu);
    lv_chart_set_next_value(chartCPU, serCPU, (lv_coord_t)d.cpu);
    lv_chart_set_next_value(chartCPU, serCPUTemp,
                            d.has_temp ? (lv_coord_t)d.cpu_temp : 0);

    lv_chart_set_next_value(chartMEMArea, serMEMArea, (lv_coord_t)d.mem);
    lv_chart_set_next_value(chartMEM, serMEM, (lv_coord_t)d.mem);

    if (d.gpu_ok) {
        lv_chart_set_next_value(chartGPUArea, serGPUArea, (lv_coord_t)d.gpu);
        lv_chart_set_next_value(chartGPU, serGPU, (lv_coord_t)d.gpu);
    }

    char b[32];
    if (d.has_temp) snprintf(b, sizeof(b), "%.0f%% %.0fC", d.cpu, d.cpu_temp);
    else            snprintf(b, sizeof(b), "%.0f%%", d.cpu);
    lv_label_set_text(vCPU, b);

    snprintf(b, sizeof(b), "%.0f%%", d.mem);
    lv_label_set_text(vMEM, b);

    if (d.gpu_ok) {
        snprintf(b, sizeof(b), "%.0f%%", d.gpu);
        lv_label_set_text(vGPU, b);
    }
}

// ============================================================
//  顶部标签
// ============================================================
void updateTopLabel() {
    String info = d.cpu_name;
    if (d.gpu_ok && d.gpu_name.length() > 0) {
        if (info.length() > 0) info += " | ";
        info += d.gpu_name;
    }
    if (info.length() > 0) {
        lv_label_set_text(topLabel, info.c_str());
        lv_obj_clear_flag(topLabel, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_label_set_text(topLabel, "");
        lv_obj_add_flag(topLabel, LV_OBJ_FLAG_HIDDEN);
    }
}

// ============================================================
//  背光
// ============================================================
void updateBacklight() {
    unsigned long now = millis();
    bool shouldOn = (now - lastSerialTime) < BL_TIMEOUT_MS;
    if (shouldOn && !backlightOn) {
        digitalWrite(PIN_BL, HIGH);
        backlightOn = true;
    } else if (!shouldOn && backlightOn) {
        digitalWrite(PIN_BL, LOW);
        backlightOn = false;
    }
}

// ============================================================
//  串口解析
// ============================================================
void handleSerial() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n') {
            if (serialBuffer.length() > 0) {
                lastSerialTime = millis();

                StaticJsonDocument<640> doc;
                DeserializationError err = deserializeJson(doc, serialBuffer);
                if (!err) {
                    if (doc.containsKey("ping")) {
                        Serial.println("{\"hello\":\"esp32c3\"}");
                        serialBuffer = "";
                        continue;
                    }

                    if (doc.containsKey("cfg")) {
                        c_bg       = parseHex(doc["bg"],     0xFFFFFF);
                        c_text     = parseHex(doc["text"],   0x202020);
                        c_text_dim = parseHex(doc["dim"],    0x909090);
                        c_grid     = parseHex(doc["grid"],   0xE8E8E8);
                        c_border   = parseHex(doc["border"], 0xD0D0D0);
                        c_cpu      = parseHex(doc["cpu"],    0x1F77B4);
                        c_mem      = parseHex(doc["mem"],    0x2CA02C);
                        c_gpu      = parseHex(doc["gpu"],    0xFF7F0E);
                        c_temp     = parseHex(doc["temp"],   0xD62728);
                        applyColorsToUI();
                        serialBuffer = "";
                        continue;
                    }

                    if (!everReceived) {
                        hideWaitScreen();
                        everReceived = true;
                    }

                    d.cpu      = doc["cpu"]      | 0.0f;
                    d.mem      = doc["mem"]      | 0.0f;
                    d.gpu      = doc["gpu"]      | 0.0f;
                    d.cpu_temp = doc["cpu_temp"] | 0.0f;
                    d.has_temp = doc["has_temp"] | false;
                    d.gpu_ok   = doc["gpu_ok"]   | false;
                    d.cpu_name = doc["cpu_name"].as<String>();
                    d.gpu_name = doc["gpu_name"].as<String>();
                    d.has_data = true;

                    updateTopLabel();
                    if (d.gpu_ok != gpuShown) applyLayout(d.gpu_ok);
                    updateCharts();
                }
                serialBuffer = "";
            }
        } else {
            serialBuffer += c;
            if (serialBuffer.length() > 600) serialBuffer = "";
        }
    }
}

// ============================================================
//  setup / loop
// ============================================================
void setup() {
    Serial.begin(115200);

    pinMode(PIN_BL, OUTPUT);
    digitalWrite(PIN_BL, HIGH);
    backlightOn = true;
    lastSerialTime = millis();

    setDefaultColors();

    tft.init();
    tft.setRotation(0);
    tft.fillScreen(TFT_WHITE);

    lv_init();
    lv_disp_draw_buf_init(&draw_buf, buf, NULL, 128 * 20);

    static lv_disp_drv_t disp_drv;
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res  = 128;
    disp_drv.ver_res  = 160;
    disp_drv.flush_cb = disp_flush;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);

    buildUI();
    Serial.println("{\"hello\":\"esp32c3\"}");
}

void loop() {
    lv_timer_handler();
    handleSerial();
    updateBacklight();
    delay(5);
}