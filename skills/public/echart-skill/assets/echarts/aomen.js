/*
* Licensed to the Apache Software Foundation (ASF) under one
* or more contributor license agreements.  See the NOTICE file
* distributed with this work for additional information
* regarding copyright ownership.  The ASF licenses this file
* to you under the Apache License, Version 2.0 (the
* "License"); you may not use this file except in compliance
* with the License.  You may obtain a copy of the License at
*
*   http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing,
* software distributed under the License is distributed on an
* "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
* KIND, either express or implied.  See the License for the
* specific language governing permissions and limitations
* under the License.
*/

(function (root, factory) {
    if (typeof define === 'function' && define.amd) {
        // AMD. Register as an anonymous module.
        define(['exports', 'echarts'], factory);
    } else if (typeof exports === 'object' && typeof exports.nodeName !== 'string') {
        // CommonJS
        factory(exports, require('echarts'));
    } else {
        // Browser globals
        factory({}, root.echarts);
    }
}(this, function (exports, echarts) {
    var log = function (msg) {
        if (typeof console !== 'undefined') {
            console && console.error && console.error(msg);
        }
    }
    if (!echarts) {
        log('ECharts is not Loaded');
        return;
    }
    if (!echarts.registerMap) {
        log('ECharts Map is not loaded')
        return;
    }
    echarts.registerMap('澳门', {"type":"FeatureCollection","features":[{"id":"820001","type":"Feature","geometry":{"type":"MultiPolygon","coordinates":[["@@LADC^umZ@DONWE@DALBBF@H@DFBBTC"],["@@P@LC@AGM@OECMBABBTCD@DDH"]],"encodeOffsets":[[[116285,22746]],[[116303,22746]]]},"properties":{"cp":[113.552965,22.207882],"name":"花地玛堂区","childNum":2}},{"id":"820002","type":"Feature","geometry":{"type":"Polygon","coordinates":["@@MK@CA@AAGDEB@NVFJG"],"encodeOffsets":[[116281,22734]]},"properties":{"cp":[113.549052,22.199175],"name":"花王堂区","childNum":1}},{"id":"820003","type":"Feature","geometry":{"type":"Polygon","coordinates":["@@EGOB@DNLHE@C"],"encodeOffsets":[[116285,22729]]},"properties":{"cp":[113.550252,22.193791],"name":"望德堂区","childNum":1}},{"id":"820004","type":"Feature","geometry":{"type":"Polygon","coordinates":["@@YMVAN@BFCBBDAFHDBBFDHIJJEFDPCHHlYJQ"],"encodeOffsets":[[116313,22707]]},"properties":{"cp":[113.55374,22.188119],"name":"大堂区","childNum":1}},{"id":"820005","type":"Feature","geometry":{"type":"Polygon","coordinates":["@@JICGAECACGEBAAEDBFNXB@"],"encodeOffsets":[[116266,22728]]},"properties":{"cp":[113.54167,22.187778],"name":"风顺堂区","childNum":1}},{"id":"820006","type":"Feature","geometry":{"type":"Polygon","coordinates":["@@ ZNWRquZCBCC@AEA@@ADCDCAACEAGBQ@INEL"],"encodeOffsets":[[116265,22694]]},"properties":{"cp":[113.558783,22.154124],"name":"嘉模堂区","childNum":1}},{"id":"820007","type":"Feature","geometry":{"type":"Polygon","coordinates":["@@MOIAIEI@@GE@AAUCBdCFIFR@HAFBBDDBDCBC@@FB@BDDDA\\M"],"encodeOffsets":[[116316,22676]]},"properties":{"cp":[113.56925,22.136546],"name":"路凼填海区","childNum":1}},{"id":"820008","type":"Feature","geometry":{"type":"Polygon","coordinates":["@@DKMMa_GC_COD@dVDBBF@@HJ@JFJBNPZK"],"encodeOffsets":[[116329,22670]]},"properties":{"cp":[113.559954,22.124049],"name":"圣方济各堂区","childNum":1}}],"UTF8Encoding":true});
}));