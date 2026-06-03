#version 300 es
precision highp float;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_progress; // 0.0 -> 1.0
uniform float u_release;  // 0.0 -> 1.0，释放回弹

out vec4 fragColor;

// Hash 和 Noise 函数用于生成微观耀斑和边缘扭曲
float hash(vec2 p) {
    vec3 p3  = fract(vec3(p.xyx) * .1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float noise(vec2 x) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

// 分形布朗运动 (FBM) 生成更细腻的纹理
float fbm(vec2 x) {
    float v = 0.0;
    float a = 0.5;
    vec2 shift = vec2(100.0);
    mat2 rot = mat2(cos(0.5), sin(0.5), -sin(0.5), cos(0.50));
    for (int i = 0; i < 4; ++i) {
        v += a * noise(x);
        x = rot * x * 2.0 + shift;
        a *= 0.5;
    }
    return v;
}

void main() {
    // 归一化坐标，将原点移至屏幕中心
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);
    float r = length(uv);
    
    // 基础半径：设定得足够大，以便将文字包裹在中心
    float baseRadius = 0.35;
    
    // 释放效果：光环轻微膨胀并消散
    float currentRadius = baseRadius * (1.0 + u_release * 0.1);
    
    // 引入低频噪声，打破内部黑色圆形的规整感，使其边缘产生有机的波动
    // 使用 uv 坐标而不是极坐标角度，避免产生接缝
    float edgeDistortion = fbm(uv * 4.0 + u_time * 0.2) * 0.03;
    float distortedR = r - edgeDistortion;
    
    // 1. 黑色圆盘 (遮挡体 / 事件视界)
    // 边缘极其锐利，内部绝对纯黑
    float disk = smoothstep(currentRadius - 0.002, currentRadius, distortedR);
    
    // 2. 日冕辉光 (Corona Glow)
    // 计算到扭曲边缘的距离
    float dist = max(0.0, distortedR - currentRadius);
    
    // 多层高斯/指数衰减，模拟真实的光学辉光
    // 内层：极度高亮，纯白
    float innerGlow = exp(-dist * 60.0) * 1.2;
    // 中层：柔和过渡，带有一点冷蓝色调
    float midGlow = exp(-dist * 15.0) * 0.6;
    // 外层：极其微弱的深空光晕
    float outerGlow = exp(-dist * 5.0) * 0.2;
    
    // 3. 微观耀斑 (Solar Flares)
    // 修复左侧半圆分界线：不使用 atan(y,x) 极坐标，而是直接使用笛卡尔坐标 uv 进行 3D 噪声采样
    // 这样可以保证在 360 度方向上都是连续的，没有任何接缝
    vec2 flareUv = normalize(uv) * (distortedR * 15.0 - u_time * 0.8);
    // 叠加一个旋转的坐标来增加动态感
    float angle = u_time * 0.1;
    mat2 rotMat = mat2(cos(angle), -sin(angle), sin(angle), cos(angle));
    vec2 rotatedUv = rotMat * uv * 8.0;
    
    float flareNoise = fbm(rotatedUv + vec2(u_time * 0.3, 0.0));
    
    // 耀斑只在靠近边缘的地方显现
    float flareMask = exp(-dist * 25.0);
    float flares = smoothstep(0.4, 0.7, flareNoise) * flareMask * 0.8;
    
    // 组合光晕颜色
    vec3 coronaColor = vec3(0.0);
    coronaColor += vec3(1.0, 1.0, 1.0) * innerGlow;       // 核心纯白
    coronaColor += vec3(0.7, 0.85, 1.0) * midGlow;        // 中层冷蓝
    coronaColor += vec3(0.15, 0.3, 0.6) * outerGlow;      // 外层深蓝
    coronaColor += vec3(0.9, 0.95, 1.0) * flares;         // 耀斑高光
    
    // 叠加黑色圆盘遮罩
    vec3 finalColor = coronaColor * disk;
    
    // 释放时的全局淡出
    finalColor *= (1.0 - u_release);
    
    fragColor = vec4(finalColor, 1.0);
}
