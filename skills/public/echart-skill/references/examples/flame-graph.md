# flame-graph

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=flame-graph
**Chart Type:** `rect`

## User Data Requirements

Columns needed: check data arrays in reference code for required format

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `stack-trace.json`:

```json
[
  {
    "name": "genunix syscall_mstate",
    "id": "b25b0d27-ce7b-44e9-b2b6-ff168a6fa36c",
    "value": 89
  },
  {
    "children": [
      {
        "children": [
          {
            "children": [
              {
                "children": [
                  {
                    "children": [
                      {
                        "children": [
                          {
                            "children": [
                              {
                               
...
```

Agent: build DuckDB query to produce matching data structure.
## Agent Workflow

1. **Analyze** user table → identify columns matching the required format above
2. **Query DuckDB** → transform to match each data array's format
3. **Replace**: use **bracket-counting** to find each `data: [...]` → replace with real data
4. **Wrap HTML**: ECharts inline + div#main + script + validate_chart.py

## Reference Code

```javascript
/*
title: Flame graph
category: custom
titleCN: 火焰图
difficulty: 4
*/
const ColorTypes = {
  root: '#8fd3e8',
  genunix: '#d95850',
  unix: '#eb8146',
  ufs: '#ffb248',
  FSS: '#f2d643',
  namefs: '#ebdba4',
  doorfs: '#fcce10',
  lofs: '#b5c334',
  zfs: '#1bca93'
};
const filterJson = (json, id) => {
  if (id == null) {
    return json;
  }
  const recur = (item, id) => {
    if (item.id === id) {
      return item;
    }
    for (const child of item.children || []) {
      const temp = recur(child, id);
      if (temp) {
        item.children = [temp];
        item.value = temp.value; // change the parents' values
        return item;
      }
    }
  };
  return recur(json, id) || json;
};
const recursionJson = (jsonObj, id) => {
  const data = [];
  const filteredJson = filterJson(structuredClone(jsonObj), id);
  const rootVal = filteredJson.value;
  const recur = (item, start = 0, level = 0) => {
    const temp = {
      name: item.id,
      // [level, start_val, end_val, name, percentage]
      value: [
        level,
        start,
        start + item.value,
        item.name,
        (item.value / rootVal) * 100
      ],
      itemStyle: {
        color: ColorTypes[item.name.split(' ')[0]]
      }
    };
    data.push(temp);
    let prevStart = start;
    for (const child of item.children || []) {
      recur(child, prevStart, level + 1);
      prevStart = prevStart + child.value;
    }
  };
  recur(filteredJson);
  return data;
};
const heightOfJson = (json) => {
  const recur = (item, level = 0) => {
    if ((item.children || []).length === 0) {
      return level;
    }
    let maxLevel = level;
    for (const child of item.children) {
      const tempLevel = recur(child, level + 1);
      maxLevel = Math.max(maxLevel, tempLevel);
    }
    return maxLevel;
  };
  return recur(json);
};
const renderItem = (params, api) => {
  const level = api.value(0);
  const start = api.coord([api.value(1), level]);
  const end = api.coord([api.value(2), level]);
  const height = ((api.size && api.size([0, 1])) || [0, 20])[1];
  const width = end[0] - start[0];
  return {
    type: 'rect',
    transition: ['shape'],
    shape: {
      x: start[0],
      y: start[1] - height / 2,
      width,
      height: height - 2 /* itemGap */,
      r: 2
    },
    style: {
      fill: api.visual('color')
    },
    emphasis: {
      style: {
        stroke: '#000'
      }
    },
    textConfig: {
      position: 'insideLeft'
    },
    textContent: {
      style: {
        text: api.value(3),
        fontFamily: 'Verdana',
        fill: '#000',
        width: width - 4,
        overflow: 'truncate',
        ellipsis: '..',
        truncateMinChar: 1
      },
      emphasis: {
        style: {
          stroke: '#000',
          lineWidth: 0.5
        }
      }
    }
  };
};
myChart.showLoading();
var stackTrace = {
  "children": [
    {
      "name": "genunix syscall_mstate",
      "id": "b25b0d27-ce7b-44e9-b2b6-ff168a6fa36c",
      "value": 89
    },
    {
      "children": [
        {
          "children": [
            {
              "children": [
                {
                  "children": [
                    {
                      "children": [
                        {
                          "children": [
                            {
                              "children": [
                                {
                                  "children": [
                                    {
                                      "name": "unix page_lookup_create",
                                      "value": 1,
                                      "id": "bb476309-a6c4-4a0c-bc63-27e8c693e9ee"
                                    }
                                  ],
                                  "name": "unix page_lookup",
                                  "value": 1,
                                  "id": "d8c76cd5-8d6f-4674-8a87-53fc31a17d23"
                                }
                              ],
                              "name": "ufs ufs_getpage",
                              "value": 1,
                              "id": "0b4e8e87-92b1-4e55-b40e-2fc6a959fa8d"
                            }
                          ],
                          "name": "genunix fop_getpage",
                          "value": 1,
                          "id": "5b374899-eadd-4da0-9669-39032726725d"
                        },
                        {
                          "children": [
                            {
                              "children": [
                                {
                                  "children": [
                                    {
                                      "children": [
                                        {
                                          "children": [
                                            {
                                              "name": "genunix pvn_plist_init",
                                              "value": 1,
                                              "id": "985f8af3-e579-47c9-b937-8141e5180d91"
                                            },
                                            {
                                              "name": "unix lgrp_mem_choose",
                                              "value": 1,
                                              "id": "89b04a7d-b28c-4434-81b4-d7cca5adb0ed"
                                            },
                                            {
                                              "children": [
                                                {
                                                  "children": [
                                                    {
                                                      "children": [
                                                        {
                                                          "name": "unix mutex_enter",
                                                          "value": 1,
                                                          "id": "6d6dfa5a-e15d-4460-aaf5-b4130062fa02"
                                                        }
                                                      ],
                                                      "name": "unix page_get_mnode_freelist",
                                                      "value": 1,
                                                      "id": "18f95faf-1e9d-4544-8171-5f594a38497b"
                                                    }
                                                  ],
                                                  "name": "unix page_get_freelist",
                                                  "value": 1,
                                                  "id": "1038d10c-a3f0-4050-95b4-0e4b7aa28877"
                                                }
                                              ],
                                              "name": "unix page_create_va",
                                              "value": 1,
                                              "id": "8e78d682-54a0-4c71-8db8-f5d5cf609e48"
                                            },
                                            {
                                              "children": [
                                                {
                                                  "name": "unix page_lookup_create",
                                                  "value": 1,
                                                  "id": "ea6aacce-7ec1-4563-b578-d46ce8998d3e"
                                                }
                                              ],
                                              "name": "unix page_lookup",
                                              "value": 1,
                                              "id": "e1ab8ac3-3be8-4419-8b27-e79a702d0933"
                                            }
                                          ],
                                          "name": "genunix swap_getapage",
                                          "value": 4,
                                          "id": "5232d249-3b1c-4cf3-8d35-6a49cdd4ca33"
                                        }
                                      ],
                                      "name": "genunix swap_getpage",
                                      "value": 4,
                                      "id": "c1d90a58-5b34-44dc-afb4-71e113aa2ad7"
                                    }
                                  ],
                                  "name": "genunix fop_getpage",
                                  "value": 4,
                                  "id": "5d89bb8b-fe36-41d6-bee5-8bc627b9d69f"
                                },
                                {
                                  "children": [
                                    {
                                      "children": [
                                        {
                                          "name": "unix hwblkclr",
                                          "value": 3,
                                          "id": "ca04aae1-5084-4a16-87aa-fd0794c5605e"
                                        }
                                      ],
                                      "name": "unix pfnzero",
                                      "value": 3,
                                      "id": "b4dabb1c-8c2f-47ce-abf2-61665adf071b"
                                    }
                                  ],
                                  "name": "unix pagezero",
                                  "value": 3,
                                  "id": "9f58da02-3eb8-4cd4-8393-2e8f33b1312a"
                                }
                              ],
                              "name": "genunix anon_zero",
                              "value": 7,
                              "id": "c3acb3b5-ec48-4101-ab89-74066ba7cf36"
                            }
                          ],
                          "name": "genunix segvn_faultpage",
                          "value": 7,
                          "id": "1a5d714f-11fa-44df-a6d0-461cc0d1ee37"
                        },
                        {
                          "name": "ufs ufs_getpage",
                          "value": 1,
                          "id": "b16f30e3-41f6-48da-b5fc-593820038c97"
                        },
                        {
                          "children": [
                            {
                              "children": [
                                {
                                  "children": [
                                    {
                                      "children": [
                                        {
                                          "children": [
                                            {
                                              "children": [
                                                {
                                                  "children": [
                                                    {
                                                      "children": [
                                                        {
                                                          "name": "unix hment_compare",
                                                          "value": 1,
                                                          "id": "2c47dc5b-a5e3-47e0-a0ed-2069bc791aa0"
                                                        }
                                                      ],
                                                      "name": "genunix avl_find",
                                                      "value": 1,
                                                      "id": "2dd5edf2-0f12-4f95-99ae-7841a1687120"
                                                    }
                                                  ],
                                                  "name": "genunix avl_add",
                                                  "value": 1,
                                                  "id": "7736b2e6-1be1-4605-b203-1100e6362d48"
                                                }
                                              ],
                                              "name": "unix hment_insert",
                                              "value": 2,
                                              "id": "79031563-629c-45ff-9356-ea54fd4c3124"
                                            }
                                          ],
                                          "name": "unix hment_assign",
                                          "value": 2,
                                          "id": "eeb48a0e-aa42-4eeb-acc9-34eee3c55a5d"
                                        }
                                      ],
                                      "name": "unix hati_pte_map",
                                      "value": 2,
                                      "id": "33419774-1ee9-4005-bc8c-5ebfb6951e55"
                                    }
                                  ],
                                  "name": "unix hati_load_common",
                                  "value": 2,
                                  "id": "966b074a-a476-4f3d-9321-679a8825e610"
                                }
                              ],
                              "name": "unix hat_memload",
                              "value": 2,
                              "id": "8a04dd2b-37f9-4f27-8f30-1f31e79fd556"
                            }
                          ],
                          "name": "unix hat_memload_region",
                          "value": 2,
                          "id": "42a7e8e5-4a76-4757-bdf1-0332d22a14fc"
                        }
                      ],
                      "name": "genunix segvn_fault",
                      "value": 11,
                      "id": "d1038d15-a8ae-4bdd-b0dc-2e71f4847948"
                    }
                  ],
                  "name": "genunix as_fault",
                  "value": 12,
                  "id": "5fa6ae34-6380-4a66-8fe5-98823f075958"
                },
                {
                  "name": "genunix segvn_fault",
                  "value": 1,
                  "id": "7c853742-390b-4201-a1db-0b5bd02bb369"
                }
              ],
              "name": "unix pagefault",
              "value": 13,
              "id": "0e50c834-9785-462a-892b-f4be8214e1b0"
            }
          ],
          "name": "unix trap",
          "value": 13,
          "id": "cb04a063-4781-487a-95b1-5b5ef22f024d"
        }
      ],
      "name": "unix 0xfffffffffb8001d6",
      "value": 13,
      "id": "f775c1e7-f63d-447c-94d4-93cf81123782"
    },
    {
      "name": "unix 0xfffffffffb800c7c",
      "value": 42,
      "id": "cb01f245-8086-4b60-987b-32b9d96b9165"
    },
    {
      "name": "unix 0xfffffffffb800c81",
      "value": 2,
      "id": "03eb77eb-7ba5-45fb-870f-022e210ef87c"
    },
    {
      "children": [
        {
          "name": "genunix gethrtime_unscaled",
          "value": 4,
          "id": "302ef61c-9ff3-4b96-bb66-cb4df88b3e80"
        },
        {
          "children": [
            {
              "children": [
                {
                  "name": "unix tsc_gethrtimeunscaled",
                  "value": 11,
                  "id": "a4cb8a3e-1f2e-4957-827c-8dbab3baca24"
                },
                {
                  "name": "unix tsc_read",
                  "value": 186,
                  "id": "f337ff3f-863f-4bd3-a357-cbeeec2505e3"
                }
              ],
              "name": "genunix gethrtime_unscaled",
              "value": 203,
              "id": "a7d2c7b9-ded7-497f-b007-e17706bdc8ee"
            },
            {
              "name": "unix tsc_gethrtimeunscaled",
              "value": 13,
              "id": "817bcceb-cbe4-4195-93dc-83ffc4ea29b5"
            }
          ],
          "name": "genunix syscall_mstate",
          "value": 355,
          "id": "1567af28-e06a-493c-9f97-0b559e207272"
        },
        {
          "name": "unix atomic_add_64",
          "value": 110,
          "id": "557c1e0a-addc-4a4c-b89e-1d3fe5a7042a"
        }
      ],
      "name": "unix 0xfffffffffb800c86",
      "value": 472,
      "id": "d4542713-1516-4105-b6be-d5d8e7e3c6bd"
    },
    {
      "children": [
        {
          "name": "genunix audit_getstate",
          "value": 27,
          "id": "a6c381c8-fcd9-4029-aa3e-38c8508a2cbe"
        },
        {
          "name": "genunix clear_stale_fd",
          "value": 10,
          "id": "f938697c-9bfa-4d16-8820-8caec831016c"
        },
        {
          "name": "genunix disp_lock_exit",
          "value": 27,
          "id": "ea1bd957-88d9-4967-a0ac-4013bc14cc0c"
        },
        {
          "children": [
            {
              "name": "FSS fss_preempt",
              "value": 1,
              "id": "4671688a-b056-4c5b-8bf5-c32dd613490f"
            },
            {
              "name": "genunix audit_getstate",
              "value": 15,
              "id": "ebfda23b-8c6f-4e5d-8991-14d979cfca7c"
            },
            {
              "name": "genunix clear_stale_fd",
              "value": 44,
              "id": "4c80bf54-1530-434f-89ec-11c12aa3696b"
            },
            {
              "children": [
                {
                  "name": "unix clear_int_flag",
                  "value": 39,
                  "id": "1392dcb0-6ba7-4ed6-9bd6-790d8a5875db"
                },
                {
                  "name": "unix do_splx",
                  "value": 1993,
                  "id": "06fdbb60-1fc2-4ba6-9a5d-9bebb3e990d9"
                },
                {
                  "children": [
                    {
                      "children": [
                        {
                          "children": [
                            {
                              "name": "unix do_splx",
                              "value": 1,
                              "id": "a779133c-110c-411c-8e4e-1d84b296dd7f"
                            }
                          ],
                          "name": "genunix disp_lock_exit_nopreempt",
                          "value": 1,
                          "id": "ecb7c991-193f-49f3-9a1d-93c70683040e"
                        }
                      ],
                      "name": "unix preempt",
                      "value": 1,
                      "id": "523a5663-fded-4e3c-b645-e85e8d9757c2"
                    }
                  ],
                  "name": "unix kpreempt",
                  "value": 1,
                  "id": "a9396bbc-fc17-4625-9121-3c021b7f8b7c"
                }
              ],
              "name": "genunix disp_lock_exit",
              "value": 2096,
              "id": "77675fcf-4bb7-4f51-9e72-67f57f9c9f42"
            },
            {
              "name": "genunix sigcheck",
              "value": 1,
              "id": "fea79d7d-1502-45f4-a537-85b436c3d330"
            },
            {
              "children": [
                {
                  "name": "unix clear_int_flag",
                  "value": 180,
                  "id": "9d0e710a-2e82-4109-bac2-bb435b4e9794"
                },
                {
                  "name": "unix splr",
                  "value": 400,
                  "id": "cf04db55-3b84-4bf2-9eec-807ec4713582"
                }
              ],
              "name": "genunix thread_lock",
              "value": 670,
              "id": "0daad78e-01ff-46dc-8bce-6ae7f558f12a"
            },
            {
              "name": "unix do_splx",
              "value": 31,
              "id": "5e8ce37d-565d-4dba-9640-1a135cca41de"
            },
            {
              "name": "unix i_ddi_splhigh",
              "value": 23,
              "id": "b8ea3383-5b64-4478-8a9c-32a42686c850"
            },
            {
              "name": "unix lock_clear_splx",
              "value": 28,
              "id": "224b4baa-6d00-481d-9d25-836283c10b4e"
            },
            {
              "name": "unix lock_try",
              "value": 778,
              "id": "9fbc0f3a-b7ba-497f-ab0d-154b9abc8810"
            },
            {
              "name": "unix lwp_getdatamodel",
              "value": 6,
              "id": "0242b08b-6992-452f-b36d-c17915b43cfc"
            },
            {
              "children": [
                {
                  "children": [
                    {
                      "children": [
                        {
                          "children": [
                            {
                              "children": [
                                {
                                  "name": "unix tsc_gethrtimeunscaled",
                                  "value": 1,
                                  "id": "b8432b71-b4b9-47e8-b044-80a8964abe62"
                                }
                              ],
                              "name": "genunix mstate_thread_onproc_time",
                              "value": 1,
                              "id": "4da6087f-2f81-438f-86c3-5f6b62a0225a"
                            }
                          ],
                          "name": "unix caps_charge_adjust",
                          "id": "1b40dc09-5b61-4e5d-8654-3b8dd2c71102",
                          "value": 1
                        }
                      ],
                      "name": "unix cpucaps_charge",
                      "value": 3,
                      "id": "8b223d48-8c80-4461-aad4-e89bc5ef3774"
                    },
                    {
                      "children": [
                        {
                          "name": "unix cmt_balance",
                          "value": 1,
                          "id": "d2d02227-fdf6-4c42-ae85-5c422109cd6e"
                        },
                        {
                          "children": [
                            {
                              "name": "unix bitset_in_set",
                              "value": 1,
                              "id": "bab1813a-3b30-4e2b-8a7b-f8f14d05a818"
                            }
                          ],
                          "name": "unix cpu_wakeup_mwait",
                          "value": 1,
                          "id": "5c5376b7-8718-4770-b562-5692a3ae3b48"
                        }
                      ],
                      "name": "unix setbackdq",
                      "value": 5,
                      "id": "169c7d7e-c805-44ad-a757-7158b53f029e"
                    }
                  ],
                  "name": "FSS fss_preempt",
                  "value": 8,
                  "id": "1508f01c-18a6-4173-b96b-100749f18363"
                },
                {
                  "name": "unix do_splx",
                  "value": 1,
                  "id": "91654d1f-9f75-4018-a6fb-61fadd2abfae"
                },
                {
                  "children": [
                    {
                      "name": "genunix disp_lock_exit_high",
                      "value": 1,
                      "id": "cf153ace-832d-407e-a417-08f7b9e04640"
                    },
                    {
                      "children": [
                        {
                          "name": "unix membar_enter",
                          "value": 1,
                          "id": "d53284f0-9d08-455f-9eda-90750eda280e"
                        }
                      ],
                      "name": "unix disp",
                      "value": 1,
                      "id": "e86559bc-abee-4f1e-adb9-4668735f4174"
                    },
                    {
                      "name": "unix do_splx",
                      "value": 1,
                      "id": "624a34e8-739d-425e-9cb2-4b84255d69ba"
                    },
                    {
                      "children": [
                        {
                          "children": [
                            {
                              "name": "genunix schedctl_save",
                              "value": 1,
                              "id": "8cbfe023-77ed-4aa4-a229-627d3a1759e5"
                            }
                          ],
                          "name": "genunix savectx",
                          "value": 2,
                          "id": "1ca6a77d-5973-4366-a1f1-6fe4529fc5eb"
                        }
                      ],
                      "name": "unix resume",
                      "value": 2,
                      "id": "16d14ec7-3c7e-478b-af7b-0e83e3c10c2c"
                    }
                  ],
                  "name": "unix swtch",
                  "value": 5,
                  "id": "518392ed-233c-48b3-b85f-594b0b4583dd"
                }
              ],
              "name": "unix preempt",
              "value": 14,
              "id": "80a6c19b-4445-46e2-a936-8c92190e7c68"
            },
            {
              "name": "unix prunstop",
              "value": 36,
              "id": "8dade592-3b02-4fce-af12-2ab6df0f2929"
            },
            {
              "name": "unix splr",
              "value": 92,
              "id": "9dc6dd7d-bb1f-4fc5-9524-94f58a0d938f"
            },
            {
              "name": "unix splx",
              "value": 6,
              "id": "c1986a81-e8fb-421e-864a-36121815c00b"
            }
          ],
          "name": "genunix post_syscall",
          "value": 4245,
          "id": "022f7903-2354-4333-99d7-dcae2c769332"
        },
        {
          "name": "genunix thread_lock",
          "value": 33,
          "id": "097552b9-7768-40c3-b1b2-843497b9af6b"
        },
        {
          "name": "unix lwp_getdatamodel",
          "value": 3,
          "id": "27c99ac9-e503-4129-aed7-6f6877eb6191"
        },
        {
          "name": "unix prunstop",
          "value": 2,
          "id": "153bf669-3ed1-43ab-80f3-07f68e6c0fe7"
        }
      ],
      "name": "unix 0xfffffffffb800c91",
      "value": 4361,
      "id": "c69602fb-4008-4ffb-93a4-2cf4f38be712"
    },
    {
      "children": [
        {
          "name": "genunix gethrtime_unscaled",
          "value": 7,
          "id": "3e52356d-42d9-4efb-bb9f-02e24bf5b870"
        },
        {
          "children": [
            {
              "children": [
                {
                  "name": "unix tsc_gethrtimeunscaled",
                  "value": 17,
                  "id": "1b4dba3b-e13f-45bc-88bd-497b2f5f5163"
                },
                {
                  "name": "unix tsc_read",
                  "value": 160,
                  "id": "3afe825e-16b5-4523-a387-fbc01fa46de9"
                }
              ],
              "name": "genunix gethrtime_unscaled",
              "value": 182,
              "id": "8038c270-2670-4838-8fd4-37714b1fb675"
            },
            {
              "name": "unix tsc_gethrtimeunscaled",
              "value": 12,
              "id": "5e8ec51c-029c-4182-b828-8b2adad8c520"
            }
          ],
          "name": "genunix syscall_mstate",
          "value": 412,
          "id": "fb9643eb-9022-45bf-a07f-c06860f53f8f"
        },
        {
          "name": "unix atomic_add_64",
          "value": 95,
          "id": "d088a382-57ef-486c-8e84-0155dbdb7061"
        }
      ],
      "name": "unix 0xfffffffffb800ca0",
      "value": 517,
      "id": "60e7cc31-07a6-4931-b678-0cff919cea6c"
    },
    {
      "name": "unix _sys_rtt",
      "value": 6,
      "id": "2ba36674-9707-448a-8e9f-0105731a0de7"
    },
    // ... (10 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
      ],
  "name": "root",
  "value": 57412,
  "id": "29509a5f-d6bc-47c9-8828-f93f5bc71d6b"
};
myChart.hideLoading();
  const levelOfOriginalJson = heightOfJson(stackTrace);
  option = {
    backgroundColor: {
      type: 'linear',
      x: 0,
      y: 0,
      x2: 0,
      y2: 1,
      colorStops: [
        {
          offset: 0.05,
          color: '#eee'
        },
        {
          offset: 0.95,
          color: '#eeeeb0'
        }
      ]
    },
    tooltip: {
      formatter: (params) => {
        const samples = params.value[2] - params.value[1];
        return `${params.marker} ${
          params.value[3]
        }: (${echarts.format.addCommas(
          samples
        )} samples, ${+params.value[4].toFixed(2)}%)`;
      }
    },
    title: [
      {
        text: 'Flame Graph',
        left: 'center',
        top: 10,
        textStyle: {
          fontFamily: 'Verdana',
          fontWeight: 'normal',
          fontSize: 20
        }
      }
    ],
    toolbox: {
      feature: {
        restore: {}
      },
      right: 20,
      top: 10
    },
    xAxis: {
      show: false
    },
    yAxis: {
      show: false,
      max: levelOfOriginalJson
    },
    series: [
      {
        type: 'custom',
        renderItem,
        encode: {
          x: [0, 1, 2],
          y: 0
        },
        data: recursionJson(stackTrace)
      }
    ]
  };
  myChart.setOption(option);
  myChart.on('click', (params) => {
    const data = recursionJson(stackTrace, params.data.name);
    const rootValue = data[0].value[2];
    myChart.setOption({
      xAxis: { max: rootValue },
      series: [{ data }]
    });
  });

```
