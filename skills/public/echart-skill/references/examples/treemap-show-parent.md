# treemap-show-parent

**Official:** https://echarts.apache.org/examples/zh/editor.html?c=treemap-show-parent
**Chart Type:** `treemap`

## User Data Requirements

Columns needed: need nested **name+value** or **name+children**

## Data Arrays — Replacement Guide

The code contains **0 data array(s)** to replace:


## External Data Format

This example uses external data. Format from `disk.tree.json`:

```json
[
  {
    "value": 40,
    "name": "Accessibility",
    "path": "Accessibility"
  },
  {
    "value": 180,
    "name": "Accounts",
    "path": "Accounts",
    "children": [
      {
        "value": 76,
        "name": "Access",
        "path": "Accounts/Access",
        "children": [
          {
            "value": 12,
            "name": "DefaultAccessPlugin.bundle",
            "path": "Accounts/Access/DefaultAccessPlugin.bundle"
          },
          {
            "value": 28,
            "
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
title: Show Parent Labels
category: treemap
titleCN: 显示父层级标签
*/
myChart.showLoading();
var diskData = [
  {
    "value": 40,
    "name": "Accessibility",
    "path": "Accessibility"
  },
  {
    "value": 180,
    "name": "Accounts",
    "path": "Accounts",
    "children": [
      {
        "value": 76,
        "name": "Access",
        "path": "Accounts/Access",
        "children": [
          {
            "value": 12,
            "name": "DefaultAccessPlugin.bundle",
            "path": "Accounts/Access/DefaultAccessPlugin.bundle"
          },
          {
            "value": 28,
            "name": "FacebookAccessPlugin.bundle",
            "path": "Accounts/Access/FacebookAccessPlugin.bundle"
          },
          {
            "value": 20,
            "name": "LinkedInAccessPlugin.bundle",
            "path": "Accounts/Access/LinkedInAccessPlugin.bundle"
          },
          {
            "value": 16,
            "name": "TencentWeiboAccessPlugin.bundle",
            "path": "Accounts/Access/TencentWeiboAccessPlugin.bundle"
          }
        ]
      },
      {
        "value": 92,
        "name": "Authentication",
        "path": "Accounts/Authentication",
        "children": [
          {
            "value": 24,
            "name": "FacebookAuthenticationPlugin.bundle",
            "path": "Accounts/Authentication/FacebookAuthenticationPlugin.bundle"
          },
          {
            "value": 16,
            "name": "LinkedInAuthenticationPlugin.bundle",
            "path": "Accounts/Authentication/LinkedInAuthenticationPlugin.bundle"
          },
          {
            "value": 20,
            "name": "TencentWeiboAuthenticationPlugin.bundle",
            "path": "Accounts/Authentication/TencentWeiboAuthenticationPlugin.bundle"
          },
          {
            "value": 16,
            "name": "TwitterAuthenticationPlugin.bundle",
            "path": "Accounts/Authentication/TwitterAuthenticationPlugin.bundle"
          },
          {
            "value": 16,
            "name": "WeiboAuthenticationPlugin.bundle",
            "path": "Accounts/Authentication/WeiboAuthenticationPlugin.bundle"
          }
        ]
      },
      {
        "value": 12,
        "name": "Notification",
        "path": "Accounts/Notification",
        "children": [
          {
            "value": 12,
            "name": "SPAAccountsNotificationPlugin.bundle",
            "path": "Accounts/Notification/SPAAccountsNotificationPlugin.bundle"
          }
        ]
      }
    ]
  },
  {
    "value": 1904,
    "name": "AddressBook Plug-Ins",
    "path": "AddressBook Plug-Ins",
    "children": [
      {
        "value": 744,
        "name": "CardDAVPlugin.sourcebundle",
        "path": "AddressBook Plug-Ins/CardDAVPlugin.sourcebundle",
        "children": [
          {
            "value": 744,
            "name": "Contents",
            "path": "AddressBook Plug-Ins/CardDAVPlugin.sourcebundle/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "DirectoryServices.sourcebundle",
        "path": "AddressBook Plug-Ins/DirectoryServices.sourcebundle",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "AddressBook Plug-Ins/DirectoryServices.sourcebundle/Contents"
          }
        ]
      },
      {
        "value": 680,
        "name": "Exchange.sourcebundle",
        "path": "AddressBook Plug-Ins/Exchange.sourcebundle",
        "children": [
          {
            "value": 680,
            "name": "Contents",
            "path": "AddressBook Plug-Ins/Exchange.sourcebundle/Contents"
          }
        ]
      },
      {
        "value": 432,
        "name": "LDAP.sourcebundle",
        "path": "AddressBook Plug-Ins/LDAP.sourcebundle",
        "children": [
          {
            "value": 432,
            "name": "Contents",
            "path": "AddressBook Plug-Ins/LDAP.sourcebundle/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "LocalSource.sourcebundle",
        "path": "AddressBook Plug-Ins/LocalSource.sourcebundle",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "AddressBook Plug-Ins/LocalSource.sourcebundle/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 36,
    "name": "Assistant",
    "path": "Assistant",
    "children": [
      {
        "value": 36,
        "name": "Plugins",
        "path": "Assistant/Plugins",
        "children": [
          {
            "value": 36,
            "name": "AddressBook.assistantBundle",
            "path": "Assistant/Plugins/AddressBook.assistantBundle"
          },
          {
            "value": 8,
            "name": "GenericAddressHandler.addresshandler",
            "path": "Recents/Plugins/GenericAddressHandler.addresshandler"
          },
          {
            "value": 12,
            "name": "MapsRecents.addresshandler",
            "path": "Recents/Plugins/MapsRecents.addresshandler"
          }
        ]
      }
    ]
  },
  {
    "value": 53228,
    "name": "Automator",
    "path": "Automator",
    "children": [
      {
        "value": 0,
        "name": "ActivateFonts.action",
        "path": "Automator/ActivateFonts.action",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "Automator/ActivateFonts.action/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "AddAttachments to Front Message.action",
        "path": "Automator/AddAttachments to Front Message.action",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Automator/AddAttachments to Front Message.action/Contents"
          }
        ]
      },
      {
        "value": 276,
        "name": "AddColor Profile.action",
        "path": "Automator/AddColor Profile.action",
        "children": [
          {
            "value": 276,
            "name": "Contents",
            "path": "Automator/AddColor Profile.action/Contents"
          }
        ]
      },
      {
        "value": 32,
        "name": "AddGrid to PDF Documents.action",
        "path": "Automator/AddGrid to PDF Documents.action",
        "children": [
          {
            "value": 32,
            "name": "Contents",
            "path": "Automator/AddGrid to PDF Documents.action/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "AddMovie to iDVD Menu.action",
        "path": "Automator/AddMovie to iDVD Menu.action",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Automator/AddMovie to iDVD Menu.action/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "AddPhotos to Album.action",
        "path": "Automator/AddPhotos to Album.action",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "Automator/AddPhotos to Album.action/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "AddSongs to iPod.action",
        "path": "Automator/AddSongs to iPod.action",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Automator/AddSongs to iPod.action/Contents"
          }
        ]
      },
      {
        "value": 44,
        "name": "AddSongs to Playlist.action",
        "path": "Automator/AddSongs to Playlist.action",
        "children": [
          {
            "value": 44,
            "name": "Contents",
            "path": "Automator/AddSongs to Playlist.action/Contents"
          }
        ]
      },
      // ... (289 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
  },
  {
    "value": 2868,
    "name": "BridgeSupport",
    "path": "BridgeSupport",
    "children": [
      {
        "value": 0,
        "name": "include",
        "path": "BridgeSupport/include"
      },
      {
        "value": 2840,
        "name": "ruby-2.0",
        "path": "BridgeSupport/ruby-2.0"
      }
    ]
  },
  {
    "value": 21988,
    "name": "Caches",
    "path": "Caches",
    "children": [
      {
        "value": 2296,
        "name": "com.apple.CVMS",
        "path": "Caches/com.apple.CVMS"
      },
      {
        "value": 19048,
        "name": "com.apple.kext.caches",
        "path": "Caches/com.apple.kext.caches",
        "children": [
          {
            "value": 12,
            "name": "Directories",
            "path": "Caches/com.apple.kext.caches/Directories"
          },
          {
            "value": 19036,
            "name": "Startup",
            "path": "Caches/com.apple.kext.caches/Startup"
          }
        ]
      }
    ]
  },
  {
    "value": 2252,
    "name": "ColorPickers",
    "path": "ColorPickers",
    "children": [
      {
        "value": 288,
        "name": "NSColorPickerCrayon.colorPicker",
        "path": "ColorPickers/NSColorPickerCrayon.colorPicker",
        "children": [
          {
            "value": 0,
            "name": "_CodeSignature",
            "path": "ColorPickers/NSColorPickerCrayon.colorPicker/_CodeSignature"
          },
          {
            "value": 288,
            "name": "Resources",
            "path": "ColorPickers/NSColorPickerCrayon.colorPicker/Resources"
          }
        ]
      },
      {
        "value": 524,
        "name": "NSColorPickerPageableNameList.colorPicker",
        "path": "ColorPickers/NSColorPickerPageableNameList.colorPicker",
        "children": [
          {
            "value": 0,
            "name": "_CodeSignature",
            "path": "ColorPickers/NSColorPickerPageableNameList.colorPicker/_CodeSignature"
          },
          {
            "value": 524,
            "name": "Resources",
            "path": "ColorPickers/NSColorPickerPageableNameList.colorPicker/Resources"
          }
        ]
      },
      {
        "value": 848,
        "name": "NSColorPickerSliders.colorPicker",
        "path": "ColorPickers/NSColorPickerSliders.colorPicker",
        "children": [
          {
            "value": 0,
            "name": "_CodeSignature",
            "path": "ColorPickers/NSColorPickerSliders.colorPicker/_CodeSignature"
          },
          {
            "value": 848,
            "name": "Resources",
            "path": "ColorPickers/NSColorPickerSliders.colorPicker/Resources"
          }
        ]
      },
      {
        "value": 532,
        "name": "NSColorPickerUser.colorPicker",
        "path": "ColorPickers/NSColorPickerUser.colorPicker",
        "children": [
          {
            "value": 0,
            "name": "_CodeSignature",
            "path": "ColorPickers/NSColorPickerUser.colorPicker/_CodeSignature"
          },
          {
            "value": 532,
            "name": "Resources",
            "path": "ColorPickers/NSColorPickerUser.colorPicker/Resources"
          }
        ]
      },
      {
        "value": 60,
        "name": "NSColorPickerWheel.colorPicker",
        "path": "ColorPickers/NSColorPickerWheel.colorPicker",
        "children": [
          {
            "value": 0,
            "name": "_CodeSignature",
            "path": "ColorPickers/NSColorPickerWheel.colorPicker/_CodeSignature"
          },
          {
            "value": 60,
            "name": "Resources",
            "path": "ColorPickers/NSColorPickerWheel.colorPicker/Resources"
          }
        ]
      }
    ]
  },
  {
    "value": 0,
    "name": "Colors",
    "path": "Colors",
    "children": [
      {
        "value": 0,
        "name": "Apple.clr",
        "path": "Colors/Apple.clr",
        "children": [
          {
            "value": 0,
            "name": "ar.lproj",
            "path": "Colors/Apple.clr/ar.lproj"
          },
          {
            "value": 0,
            "name": "ca.lproj",
            "path": "Colors/Apple.clr/ca.lproj"
          },
          {
            "value": 0,
            "name": "cs.lproj",
            "path": "Colors/Apple.clr/cs.lproj"
          },
          {
            "value": 0,
            "name": "da.lproj",
            "path": "Colors/Apple.clr/da.lproj"
          },
          {
            "value": 0,
            "name": "Dutch.lproj",
            "path": "Colors/Apple.clr/Dutch.lproj"
          },
          {
            "value": 0,
            "name": "el.lproj",
            "path": "Colors/Apple.clr/el.lproj"
          },
          {
            "value": 0,
            "name": "English.lproj",
            "path": "Colors/Apple.clr/English.lproj"
          },
          {
            "value": 0,
            "name": "fi.lproj",
            "path": "Colors/Apple.clr/fi.lproj"
          },
          {
            "value": 0,
            "name": "French.lproj",
            "path": "Colors/Apple.clr/French.lproj"
          },
          {
            "value": 0,
            "name": "German.lproj",
            "path": "Colors/Apple.clr/German.lproj"
          },
          {
            "value": 0,
            "name": "he.lproj",
            "path": "Colors/Apple.clr/he.lproj"
          },
          {
            "value": 0,
            "name": "hr.lproj",
            "path": "Colors/Apple.clr/hr.lproj"
          },
          {
            "value": 0,
            "name": "hu.lproj",
            "path": "Colors/Apple.clr/hu.lproj"
          },
          {
            "value": 0,
            "name": "id.lproj",
            "path": "Colors/Apple.clr/id.lproj"
          },
          {
            "value": 0,
            "name": "Italian.lproj",
            "path": "Colors/Apple.clr/Italian.lproj"
          },
          {
            "value": 0,
            "name": "Japanese.lproj",
            "path": "Colors/Apple.clr/Japanese.lproj"
          },
          {
            "value": 0,
            "name": "ko.lproj",
            "path": "Colors/Apple.clr/ko.lproj"
          },
          {
            "value": 0,
            "name": "ms.lproj",
            "path": "Colors/Apple.clr/ms.lproj"
          },
          {
            "value": 0,
            "name": "no.lproj",
            "path": "Colors/Apple.clr/no.lproj"
          },
          {
            "value": 0,
            "name": "pl.lproj",
            "path": "Colors/Apple.clr/pl.lproj"
          },
          {
            "value": 0,
            "name": "pt.lproj",
            "path": "Colors/Apple.clr/pt.lproj"
          },
          {
            "value": 0,
            "name": "pt_PT.lproj",
            "path": "Colors/Apple.clr/pt_PT.lproj"
          },
          {
            "value": 0,
            "name": "ro.lproj",
            "path": "Colors/Apple.clr/ro.lproj"
          },
          {
            "value": 0,
            "name": "ru.lproj",
            "path": "Colors/Apple.clr/ru.lproj"
          },
          {
            "value": 0,
            "name": "sk.lproj",
            "path": "Colors/Apple.clr/sk.lproj"
          },
          {
            "value": 0,
            "name": "Spanish.lproj",
            "path": "Colors/Apple.clr/Spanish.lproj"
          },
          {
            "value": 0,
            "name": "sv.lproj",
            "path": "Colors/Apple.clr/sv.lproj"
          },
          {
            "value": 0,
            "name": "th.lproj",
            "path": "Colors/Apple.clr/th.lproj"
          },
          {
            "value": 0,
            "name": "tr.lproj",
            "path": "Colors/Apple.clr/tr.lproj"
          },
          {
            "value": 0,
            "name": "uk.lproj",
            "path": "Colors/Apple.clr/uk.lproj"
          },
          {
            "value": 0,
            "name": "vi.lproj",
            "path": "Colors/Apple.clr/vi.lproj"
          },
          {
            "value": 0,
            "name": "zh_CN.lproj",
            "path": "Colors/Apple.clr/zh_CN.lproj"
          },
          {
            "value": 0,
            "name": "zh_TW.lproj",
            "path": "Colors/Apple.clr/zh_TW.lproj"
          }
        ]
      },
      {
        "value": 0,
        "name": "Crayons.clr",
        "path": "Colors/Crayons.clr",
        "children": [
          {
            "value": 0,
            "name": "ar.lproj",
            "path": "Colors/Crayons.clr/ar.lproj"
          },
          {
            "value": 0,
            "name": "ca.lproj",
            "path": "Colors/Crayons.clr/ca.lproj"
          },
          {
            "value": 0,
            "name": "cs.lproj",
            "path": "Colors/Crayons.clr/cs.lproj"
          },
          {
            "value": 0,
            "name": "da.lproj",
            "path": "Colors/Crayons.clr/da.lproj"
          },
          {
            "value": 0,
            "name": "Dutch.lproj",
            "path": "Colors/Crayons.clr/Dutch.lproj"
          },
          {
            "value": 0,
            "name": "el.lproj",
            "path": "Colors/Crayons.clr/el.lproj"
          },
          {
            "value": 0,
            "name": "English.lproj",
            "path": "Colors/Crayons.clr/English.lproj"
          },
          {
            "value": 0,
            "name": "fi.lproj",
            "path": "Colors/Crayons.clr/fi.lproj"
          },
          {
            "value": 0,
            "name": "French.lproj",
            "path": "Colors/Crayons.clr/French.lproj"
          },
          {
            "value": 0,
            "name": "German.lproj",
            "path": "Colors/Crayons.clr/German.lproj"
          },
          {
            "value": 0,
            "name": "he.lproj",
            "path": "Colors/Crayons.clr/he.lproj"
          },
          {
            "value": 0,
            "name": "hr.lproj",
            "path": "Colors/Crayons.clr/hr.lproj"
          },
          {
            "value": 0,
            "name": "hu.lproj",
            "path": "Colors/Crayons.clr/hu.lproj"
          },
          {
            "value": 0,
            "name": "id.lproj",
            "path": "Colors/Crayons.clr/id.lproj"
          },
          {
            "value": 0,
            "name": "Italian.lproj",
            "path": "Colors/Crayons.clr/Italian.lproj"
          },
          {
            "value": 0,
            "name": "Japanese.lproj",
            "path": "Colors/Crayons.clr/Japanese.lproj"
          },
          {
            "value": 0,
            "name": "ko.lproj",
            "path": "Colors/Crayons.clr/ko.lproj"
          },
          {
            "value": 0,
            "name": "ms.lproj",
            "path": "Colors/Crayons.clr/ms.lproj"
          },
          {
            "value": 0,
            "name": "no.lproj",
            "path": "Colors/Crayons.clr/no.lproj"
          },
          {
            "value": 0,
            "name": "pl.lproj",
            "path": "Colors/Crayons.clr/pl.lproj"
          },
          {
            "value": 0,
            "name": "pt.lproj",
            "path": "Colors/Crayons.clr/pt.lproj"
          },
          {
            "value": 0,
            "name": "pt_PT.lproj",
            "path": "Colors/Crayons.clr/pt_PT.lproj"
          },
          {
            "value": 0,
            "name": "ro.lproj",
            "path": "Colors/Crayons.clr/ro.lproj"
          },
          {
            "value": 0,
            "name": "ru.lproj",
            "path": "Colors/Crayons.clr/ru.lproj"
          },
          {
            "value": 0,
            "name": "sk.lproj",
            "path": "Colors/Crayons.clr/sk.lproj"
          },
          {
            "value": 0,
            "name": "Spanish.lproj",
            "path": "Colors/Crayons.clr/Spanish.lproj"
          },
          {
            "value": 0,
            "name": "sv.lproj",
            "path": "Colors/Crayons.clr/sv.lproj"
          },
          {
            "value": 0,
            "name": "th.lproj",
            "path": "Colors/Crayons.clr/th.lproj"
          },
          {
            "value": 0,
            "name": "tr.lproj",
            "path": "Colors/Crayons.clr/tr.lproj"
          },
          {
            "value": 0,
            "name": "uk.lproj",
            "path": "Colors/Crayons.clr/uk.lproj"
          },
          {
            "value": 0,
            "name": "vi.lproj",
            "path": "Colors/Crayons.clr/vi.lproj"
          },
          {
            "value": 0,
            "name": "zh_CN.lproj",
            "path": "Colors/Crayons.clr/zh_CN.lproj"
          },
          {
            "value": 0,
            "name": "zh_TW.lproj",
            "path": "Colors/Crayons.clr/zh_TW.lproj"
          }
        ]
      },
      {
        "value": 0,
        "name": "System.clr",
        "path": "Colors/System.clr",
        "children": [
          {
            "value": 0,
            "name": "ar.lproj",
            "path": "Colors/System.clr/ar.lproj"
          },
          {
            "value": 0,
            "name": "ca.lproj",
            "path": "Colors/System.clr/ca.lproj"
          },
          {
            "value": 0,
            "name": "cs.lproj",
            "path": "Colors/System.clr/cs.lproj"
          },
          {
            "value": 0,
            "name": "da.lproj",
            "path": "Colors/System.clr/da.lproj"
          },
          {
            "value": 0,
            "name": "Dutch.lproj",
            "path": "Colors/System.clr/Dutch.lproj"
          },
          {
            "value": 0,
            "name": "el.lproj",
            "path": "Colors/System.clr/el.lproj"
          },
          {
            "value": 0,
            "name": "English.lproj",
            "path": "Colors/System.clr/English.lproj"
          },
          {
            "value": 0,
            "name": "fi.lproj",
            "path": "Colors/System.clr/fi.lproj"
          },
          {
            "value": 0,
            "name": "French.lproj",
            "path": "Colors/System.clr/French.lproj"
          },
          {
            "value": 0,
            "name": "German.lproj",
            "path": "Colors/System.clr/German.lproj"
          },
          {
            "value": 0,
            "name": "he.lproj",
            "path": "Colors/System.clr/he.lproj"
          },
          {
            "value": 0,
            "name": "hr.lproj",
            "path": "Colors/System.clr/hr.lproj"
          },
          {
            "value": 0,
            "name": "hu.lproj",
            "path": "Colors/System.clr/hu.lproj"
          },
          {
            "value": 0,
            "name": "id.lproj",
            "path": "Colors/System.clr/id.lproj"
          },
          {
            "value": 0,
            "name": "Italian.lproj",
            "path": "Colors/System.clr/Italian.lproj"
          },
          {
            "value": 0,
            "name": "Japanese.lproj",
            "path": "Colors/System.clr/Japanese.lproj"
          },
          {
            "value": 0,
            "name": "ko.lproj",
            "path": "Colors/System.clr/ko.lproj"
          },
          {
            "value": 0,
            "name": "ms.lproj",
            "path": "Colors/System.clr/ms.lproj"
          },
          {
            "value": 0,
            "name": "no.lproj",
            "path": "Colors/System.clr/no.lproj"
          },
          {
            "value": 0,
            "name": "pl.lproj",
            "path": "Colors/System.clr/pl.lproj"
          },
          {
            "value": 0,
            "name": "pt.lproj",
            "path": "Colors/System.clr/pt.lproj"
          },
          {
            "value": 0,
            "name": "pt_PT.lproj",
            "path": "Colors/System.clr/pt_PT.lproj"
          },
          {
            "value": 0,
            "name": "ro.lproj",
            "path": "Colors/System.clr/ro.lproj"
          },
          {
            "value": 0,
            "name": "ru.lproj",
            "path": "Colors/System.clr/ru.lproj"
          },
          {
            "value": 0,
            "name": "sk.lproj",
            "path": "Colors/System.clr/sk.lproj"
          },
          {
            "value": 0,
            "name": "Spanish.lproj",
            "path": "Colors/System.clr/Spanish.lproj"
          },
          {
            "value": 0,
            "name": "sv.lproj",
            "path": "Colors/System.clr/sv.lproj"
          },
          {
            "value": 0,
            "name": "th.lproj",
            "path": "Colors/System.clr/th.lproj"
          },
          {
            "value": 0,
            "name": "tr.lproj",
            "path": "Colors/System.clr/tr.lproj"
          },
          {
            "value": 0,
            "name": "uk.lproj",
            "path": "Colors/System.clr/uk.lproj"
          },
          {
            "value": 0,
            "name": "vi.lproj",
            "path": "Colors/System.clr/vi.lproj"
          },
          {
            "value": 0,
            "name": "zh_CN.lproj",
            "path": "Colors/System.clr/zh_CN.lproj"
          },
          {
            "value": 0,
            "name": "zh_TW.lproj",
            "path": "Colors/System.clr/zh_TW.lproj"
          }
        ]
      }
    ]
  },
  {
    "value": 2908,
    "name": "ColorSync",
    "path": "ColorSync",
    "children": [
      {
        "value": 2868,
        "name": "Calibrators",
        "path": "ColorSync/Calibrators",
        "children": [
          {
            "value": 2868,
            "name": "DisplayCalibrator.app",
            "path": "ColorSync/Calibrators/DisplayCalibrator.app"
          }
        ]
      },
      {
        "value": 40,
        "name": "Profiles",
        "path": "ColorSync/Profiles"
      }
    ]
  },
  {
    "value": 21772,
    "name": "Components",
    "path": "Components",
    "children": [
      {
        "value": 416,
        "name": "AppleScript.component",
        "path": "Components/AppleScript.component",
        "children": [
          {
            "value": 416,
            "name": "Contents",
            "path": "Components/AppleScript.component/Contents"
          }
        ]
      },
      {
        "value": 2592,
        "name": "AudioCodecs.component",
        "path": "Components/AudioCodecs.component",
        "children": [
          {
            "value": 2592,
            "name": "Contents",
            "path": "Components/AudioCodecs.component/Contents"
          }
        ]
      },
      {
        "value": 92,
        "name": "AUSpeechSynthesis.component",
        "path": "Components/AUSpeechSynthesis.component",
        "children": [
          {
            "value": 92,
            "name": "Contents",
            "path": "Components/AUSpeechSynthesis.component/Contents"
          }
        ]
      },
      {
        "value": 18492,
        "name": "CoreAudio.component",
        "path": "Components/CoreAudio.component",
        "children": [
          {
            "value": 18492,
            "name": "Contents",
            "path": "Components/CoreAudio.component/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "IOFWDVComponents.component",
        "path": "Components/IOFWDVComponents.component",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "Components/IOFWDVComponents.component/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "IOQTComponents.component",
        "path": "Components/IOQTComponents.component",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "Components/IOQTComponents.component/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "PDFImporter.component",
        "path": "Components/PDFImporter.component",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Components/PDFImporter.component/Contents"
          }
        ]
      },
      {
        "value": 120,
        "name": "SoundManagerComponents.component",
        "path": "Components/SoundManagerComponents.component",
        "children": [
          {
            "value": 120,
            "name": "Contents",
            "path": "Components/SoundManagerComponents.component/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 45728,
    "name": "Compositions",
    "path": "Compositions",
    "children": [
      {
        "value": 0,
        "name": ".Localization.bundle",
        "path": "Compositions/.Localization.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "Compositions/.Localization.bundle/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 409060,
    "name": "CoreServices",
    "path": "CoreServices",
    "children": [
      {
        "value": 1152,
        "name": "AddPrinter.app",
        "path": "CoreServices/AddPrinter.app",
        "children": [
          {
            "value": 1152,
            "name": "Contents",
            "path": "CoreServices/AddPrinter.app/Contents"
          }
        ]
      },
      {
        "value": 72,
        "name": "AddressBookUrlForwarder.app",
        "path": "CoreServices/AddressBookUrlForwarder.app",
        "children": [
          {
            "value": 72,
            "name": "Contents",
            "path": "CoreServices/AddressBookUrlForwarder.app/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "AirPlayUIAgent.app",
        "path": "CoreServices/AirPlayUIAgent.app",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "CoreServices/AirPlayUIAgent.app/Contents"
          }
        ]
      },
      {
        "value": 56,
        "name": "AirPortBase Station Agent.app",
        "path": "CoreServices/AirPortBase Station Agent.app",
        "children": [
          {
            "value": 56,
            "name": "Contents",
            "path": "CoreServices/AirPortBase Station Agent.app/Contents"
          }
        ]
      },
      {
        "value": 92,
        "name": "AOS.bundle",
        "path": "CoreServices/AOS.bundle",
        "children": [
          {
            "value": 92,
            "name": "Contents",
            "path": "CoreServices/AOS.bundle/Contents"
          }
        ]
      },
      {
        "value": 1564,
        "name": "AppDownloadLauncher.app",
        "path": "CoreServices/AppDownloadLauncher.app",
        "children": [
          {
            "value": 1564,
            "name": "Contents",
            "path": "CoreServices/AppDownloadLauncher.app/Contents"
          }
        ]
      },
      {
        "value": 376,
        "name": "Apple80211Agent.app",
        "path": "CoreServices/Apple80211Agent.app",
        "children": [
          {
            "value": 376,
            "name": "Contents",
            "path": "CoreServices/Apple80211Agent.app/Contents"
          }
        ]
      },
      {
        "value": 480,
        "name": "AppleFileServer.app",
        "path": "CoreServices/AppleFileServer.app",
        "children": [
          {
            "value": 480,
            "name": "Contents",
            "path": "CoreServices/AppleFileServer.app/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "AppleGraphicsWarning.app",
        "path": "CoreServices/AppleGraphicsWarning.app",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "CoreServices/AppleGraphicsWarning.app/Contents"
          }
        ]
      },
      {
        "value": 1752,
        "name": "AppleScriptUtility.app",
        "path": "CoreServices/AppleScriptUtility.app",
        "children": [
          {
            "value": 1752,
            "name": "Contents",
            "path": "CoreServices/AppleScriptUtility.app/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "ApplicationFirewall.bundle",
        "path": "CoreServices/ApplicationFirewall.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "CoreServices/ApplicationFirewall.bundle/Contents"
          }
        ]
      },
      {
        "value": 14808,
        "name": "Applications",
        "path": "CoreServices/Applications",
        "children": [
          {
            "value": 1792,
            "name": "NetworkUtility.app",
            "path": "CoreServices/Applications/NetworkUtility.app"
          },
          {
            "value": 7328,
            "name": "RAIDUtility.app",
            "path": "CoreServices/Applications/RAIDUtility.app"
          },
          {
            "value": 5688,
            "name": "WirelessDiagnostics.app",
            "path": "CoreServices/Applications/WirelessDiagnostics.app"
          }
        ]
      },
      {
        "value": 6620,
        "name": "ArchiveUtility.app",
        "path": "CoreServices/ArchiveUtility.app",
        "children": [
          {
            "value": 6620,
            "name": "Contents",
            "path": "CoreServices/ArchiveUtility.app/Contents"
          }
        ]
      },
      {
        "value": 24,
        "name": "AutomatorLauncher.app",
        "path": "CoreServices/AutomatorLauncher.app",
        "children": [
          {
            "value": 24,
            "name": "Contents",
            "path": "CoreServices/AutomatorLauncher.app/Contents"
          }
        ]
      },
      {
        "value": 584,
        "name": "AutomatorRunner.app",
        "path": "CoreServices/AutomatorRunner.app",
        "children": [
          {
            "value": 584,
            "name": "Contents",
            "path": "CoreServices/AutomatorRunner.app/Contents"
          }
        ]
      },
      {
        "value": 412,
        "name": "AVRCPAgent.app",
        "path": "CoreServices/AVRCPAgent.app",
        "children": [
          {
            "value": 412,
            "name": "Contents",
            "path": "CoreServices/AVRCPAgent.app/Contents"
          }
        ]
      },
      {
        "value": 1400,
        "name": "backupd.bundle",
        "path": "CoreServices/backupd.bundle",
        "children": [
          {
            "value": 1400,
            "name": "Contents",
            "path": "CoreServices/backupd.bundle/Contents"
          }
        ]
      },
      {
        "value": 2548,
        "name": "BluetoothSetup Assistant.app",
        "path": "CoreServices/BluetoothSetup Assistant.app",
        "children": [
          {
            "value": 2548,
            "name": "Contents",
            "path": "CoreServices/BluetoothSetup Assistant.app/Contents"
          }
        ]
      },
      {
        "value": 2588,
        "name": "BluetoothUIServer.app",
        "path": "CoreServices/BluetoothUIServer.app",
        "children": [
          {
            "value": 2588,
            "name": "Contents",
            "path": "CoreServices/BluetoothUIServer.app/Contents"
          }
        ]
      },
      {
        "value": 1288,
        "name": "CalendarFileHandler.app",
        "path": "CoreServices/CalendarFileHandler.app",
        "children": [
          {
            "value": 1288,
            "name": "Contents",
            "path": "CoreServices/CalendarFileHandler.app/Contents"
          }
        ]
      },
      {
        "value": 44,
        "name": "CaptiveNetwork Assistant.app",
        "path": "CoreServices/CaptiveNetwork Assistant.app",
        "children": [
          {
            "value": 44,
            "name": "Contents",
            "path": "CoreServices/CaptiveNetwork Assistant.app/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "CarbonSpellChecker.bundle",
        "path": "CoreServices/CarbonSpellChecker.bundle",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "CoreServices/CarbonSpellChecker.bundle/Contents"
          }
        ]
      },
      {
        "value": 27144,
        "name": "CertificateAssistant.app",
        "path": "CoreServices/CertificateAssistant.app",
        "children": [
          {
            "value": 27144,
            "name": "Contents",
            "path": "CoreServices/CertificateAssistant.app/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "CommonCocoaPanels.bundle",
        "path": "CoreServices/CommonCocoaPanels.bundle",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "CoreServices/CommonCocoaPanels.bundle/Contents"
          }
        ]
      },
      {
        "value": 676,
        "name": "CoreLocationAgent.app",
        "path": "CoreServices/CoreLocationAgent.app",
        "children": [
          {
            "value": 676,
            "name": "Contents",
            "path": "CoreServices/CoreLocationAgent.app/Contents"
          }
        ]
      },
      {
        "value": 164,
        "name": "CoreServicesUIAgent.app",
        "path": "CoreServices/CoreServicesUIAgent.app",
        "children": [
          {
            "value": 164,
            "name": "Contents",
            "path": "CoreServices/CoreServicesUIAgent.app/Contents"
          }
        ]
      },
      {
        "value": 171300,
        "name": "CoreTypes.bundle",
        "path": "CoreServices/CoreTypes.bundle",
        "children": [
          {
            "value": 171300,
            "name": "Contents",
            "path": "CoreServices/CoreTypes.bundle/Contents"
          }
        ]
      },
      {
        "value": 308,
        "name": "DatabaseEvents.app",
        "path": "CoreServices/DatabaseEvents.app",
        "children": [
          {
            "value": 308,
            "name": "Contents",
            "path": "CoreServices/DatabaseEvents.app/Contents"
          }
        ]
      },
      {
        "value": 6104,
        "name": "DirectoryUtility.app",
        "path": "CoreServices/DirectoryUtility.app",
        "children": [
          {
            "value": 6104,
            "name": "Contents",
            "path": "CoreServices/DirectoryUtility.app/Contents"
          }
        ]
      },
      {
        "value": 1840,
        "name": "DiskImageMounter.app",
        "path": "CoreServices/DiskImageMounter.app",
        "children": [
          {
            "value": 1840,
            "name": "Contents",
            "path": "CoreServices/DiskImageMounter.app/Contents"
          }
        ]
      },
      {
        "value": 8476,
        "name": "Dock.app",
        "path": "CoreServices/Dock.app",
        "children": [
          {
            "value": 8476,
            "name": "Contents",
            "path": "CoreServices/Dock.app/Contents"
          }
        ]
      },
      {
        "value": 696,
        "name": "Encodings",
        "path": "CoreServices/Encodings"
      },
      {
        "value": 1024,
        "name": "ExpansionSlot Utility.app",
        "path": "CoreServices/ExpansionSlot Utility.app",
        "children": [
          {
            "value": 1024,
            "name": "Contents",
            "path": "CoreServices/ExpansionSlot Utility.app/Contents"
          }
        ]
      },
      {
        "value": 1732,
        "name": "FileSync.app",
        "path": "CoreServices/FileSync.app",
        "children": [
          {
            "value": 1732,
            "name": "Contents",
            "path": "CoreServices/FileSync.app/Contents"
          }
        ]
      },
      {
        "value": 572,
        "name": "FileSyncAgent.app",
        "path": "CoreServices/FileSyncAgent.app",
        "children": [
          {
            "value": 572,
            "name": "Contents",
            "path": "CoreServices/FileSyncAgent.app/Contents"
          }
        ]
      },
      {
        "value": 35168,
        "name": "Finder.app",
        "path": "CoreServices/Finder.app",
        "children": [
          {
            "value": 35168,
            "name": "Contents",
            "path": "CoreServices/Finder.app/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "FirmwareUpdates",
        "path": "CoreServices/FirmwareUpdates"
      },
      {
        "value": 336,
        "name": "FolderActions Dispatcher.app",
        "path": "CoreServices/FolderActions Dispatcher.app",
        "children": [
          {
            "value": 336,
            "name": "Contents",
            "path": "CoreServices/FolderActions Dispatcher.app/Contents"
          }
        ]
      },
      {
        "value": 1820,
        "name": "FolderActions Setup.app",
        "path": "CoreServices/FolderActions Setup.app",
        "children": [
          {
            "value": 1820,
            "name": "Contents",
            "path": "CoreServices/FolderActions Setup.app/Contents"
          }
        ]
      },
      {
        "value": 3268,
        "name": "HelpViewer.app",
        "path": "CoreServices/HelpViewer.app",
        "children": [
          {
            "value": 3268,
            "name": "Contents",
            "path": "CoreServices/HelpViewer.app/Contents"
          }
        ]
      },
      {
        "value": 352,
        "name": "ImageEvents.app",
        "path": "CoreServices/ImageEvents.app",
        "children": [
          {
            "value": 352,
            "name": "Contents",
            "path": "CoreServices/ImageEvents.app/Contents"
          }
        ]
      },
      {
        "value": 2012,
        "name": "InstallCommand Line Developer Tools.app",
        "path": "CoreServices/InstallCommand Line Developer Tools.app",
        "children": [
          {
            "value": 2012,
            "name": "Contents",
            "path": "CoreServices/InstallCommand Line Developer Tools.app/Contents"
          }
        ]
      },
      {
        "value": 108,
        "name": "Installin Progress.app",
        "path": "CoreServices/Installin Progress.app",
        "children": [
          {
            "value": 108,
            "name": "Contents",
            "path": "CoreServices/Installin Progress.app/Contents"
          }
        ]
      },
      {
        "value": 7444,
        "name": "Installer.app",
        "path": "CoreServices/Installer.app",
        "children": [
          {
            "value": 7444,
            "name": "Contents",
            "path": "CoreServices/Installer.app/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "InstallerStatusNotifications.bundle",
        "path": "CoreServices/InstallerStatusNotifications.bundle",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "CoreServices/InstallerStatusNotifications.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "InternetSharing.bundle",
        "path": "CoreServices/InternetSharing.bundle",
        "children": [
          {
            "value": 0,
            "name": "Resources",
            "path": "CoreServices/InternetSharing.bundle/Resources"
          }
        ]
      },
      {
        "value": 244,
        "name": "JarLauncher.app",
        "path": "CoreServices/JarLauncher.app",
        "children": [
          {
            "value": 244,
            "name": "Contents",
            "path": "CoreServices/JarLauncher.app/Contents"
          }
        ]
      },
      {
        "value": 152,
        "name": "JavaWeb Start.app",
        "path": "CoreServices/JavaWeb Start.app",
        "children": [
          {
            "value": 152,
            "name": "Contents",
            "path": "CoreServices/JavaWeb Start.app/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "KernelEventAgent.bundle",
        "path": "CoreServices/KernelEventAgent.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "CoreServices/KernelEventAgent.bundle/Contents"
          },
          {
            "value": 12,
            "name": "FileSystemUIAgent.app",
            "path": "CoreServices/KernelEventAgent.bundle/FileSystemUIAgent.app"
          }
        ]
      },
      {
        "value": 1016,
        "name": "KeyboardSetupAssistant.app",
        "path": "CoreServices/KeyboardSetupAssistant.app",
        "children": [
          {
            "value": 1016,
            "name": "Contents",
            "path": "CoreServices/KeyboardSetupAssistant.app/Contents"
          }
        ]
      },
      {
        "value": 840,
        "name": "KeychainCircle Notification.app",
        "path": "CoreServices/KeychainCircle Notification.app",
        "children": [
          {
            "value": 840,
            "name": "Contents",
            "path": "CoreServices/KeychainCircle Notification.app/Contents"
          }
        ]
      },
      {
        "value": 1448,
        "name": "LanguageChooser.app",
        "path": "CoreServices/LanguageChooser.app",
        "children": [
          {
            "value": 1448,
            "name": "Contents",
            "path": "CoreServices/LanguageChooser.app/Contents"
          }
        ]
      },
      {
        "value": 868,
        "name": "LocationMenu.app",
        "path": "CoreServices/LocationMenu.app",
        "children": [
          {
            "value": 868,
            "name": "Contents",
            "path": "CoreServices/LocationMenu.app/Contents"
          }
        ]
      },
      {
        "value": 8260,
        "name": "loginwindow.app",
        "path": "CoreServices/loginwindow.app",
        "children": [
          {
            "value": 8260,
            "name": "Contents",
            "path": "CoreServices/loginwindow.app/Contents"
          }
        ]
      },
      {
        "value": 3632,
        "name": "ManagedClient.app",
        "path": "CoreServices/ManagedClient.app",
        "children": [
          {
            "value": 3632,
            "name": "Contents",
            "path": "CoreServices/ManagedClient.app/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "mDNSResponder.bundle",
        "path": "CoreServices/mDNSResponder.bundle",
        "children": [
          {
            "value": 0,
            "name": "Resources",
            "path": "CoreServices/mDNSResponder.bundle/Resources"
          }
        ]
      },
      {
        "value": 420,
        "name": "MemorySlot Utility.app",
        "path": "CoreServices/MemorySlot Utility.app",
        "children": [
          {
            "value": 420,
            "name": "Contents",
            "path": "CoreServices/MemorySlot Utility.app/Contents"
          }
        ]
      },
      {
        "value": 4272,
        "name": "MenuExtras",
        "path": "CoreServices/MenuExtras",
        "children": [
          {
            "value": 416,
            "name": "AirPort.menu",
            "path": "CoreServices/MenuExtras/AirPort.menu"
          },
          {
            "value": 788,
            "name": "Battery.menu",
            "path": "CoreServices/MenuExtras/Battery.menu"
          },
          {
            "value": 112,
            "name": "Bluetooth.menu",
            "path": "CoreServices/MenuExtras/Bluetooth.menu"
          },
          {
            "value": 12,
            "name": "Clock.menu",
            "path": "CoreServices/MenuExtras/Clock.menu"
          },
          {
            "value": 84,
            "name": "Displays.menu",
            "path": "CoreServices/MenuExtras/Displays.menu"
          },
          {
            "value": 32,
            "name": "Eject.menu",
            "path": "CoreServices/MenuExtras/Eject.menu"
          },
          {
            "value": 24,
            "name": "ExpressCard.menu",
            "path": "CoreServices/MenuExtras/ExpressCard.menu"
          },
          {
            "value": 76,
            "name": "Fax.menu",
            "path": "CoreServices/MenuExtras/Fax.menu"
          },
          {
            "value": 112,
            "name": "HomeSync.menu",
            "path": "CoreServices/MenuExtras/HomeSync.menu"
          },
          {
            "value": 84,
            "name": "iChat.menu",
            "path": "CoreServices/MenuExtras/iChat.menu"
          },
          {
            "value": 28,
            "name": "Ink.menu",
            "path": "CoreServices/MenuExtras/Ink.menu"
          },
          {
            "value": 104,
            "name": "IrDA.menu",
            "path": "CoreServices/MenuExtras/IrDA.menu"
          },
          {
            "value": 68,
            "name": "PPP.menu",
            "path": "CoreServices/MenuExtras/PPP.menu"
          },
          {
            "value": 24,
            "name": "PPPoE.menu",
            "path": "CoreServices/MenuExtras/PPPoE.menu"
          },
          {
            "value": 60,
            "name": "RemoteDesktop.menu",
            "path": "CoreServices/MenuExtras/RemoteDesktop.menu"
          },
          {
            "value": 48,
            "name": "Script Menu.menu",
            "path": "CoreServices/MenuExtras/Script Menu.menu"
          },
          {
            "value": 832,
            "name": "TextInput.menu",
            "path": "CoreServices/MenuExtras/TextInput.menu"
          },
          {
            "value": 144,
            "name": "TimeMachine.menu",
            "path": "CoreServices/MenuExtras/TimeMachine.menu"
          },
          {
            "value": 40,
            "name": "UniversalAccess.menu",
            "path": "CoreServices/MenuExtras/UniversalAccess.menu"
          },
          {
            "value": 108,
            "name": "User.menu",
            "path": "CoreServices/MenuExtras/User.menu"
          },
          {
            "value": 316,
            "name": "Volume.menu",
            "path": "CoreServices/MenuExtras/Volume.menu"
          },
          {
            "value": 48,
            "name": "VPN.menu",
            "path": "CoreServices/MenuExtras/VPN.menu"
          },
          {
            "value": 712,
            "name": "WWAN.menu",
            "path": "CoreServices/MenuExtras/WWAN.menu"
          }
        ]
      },
      {
        "value": 16,
        "name": "MLTEFile.bundle",
        "path": "CoreServices/MLTEFile.bundle",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "CoreServices/MLTEFile.bundle/Contents"
          }
        ]
      },
      {
        "value": 616,
        "name": "MRTAgent.app",
        "path": "CoreServices/MRTAgent.app",
        "children": [
          {
            "value": 616,
            "name": "Contents",
            "path": "CoreServices/MRTAgent.app/Contents"
          }
        ]
      },
      {
        "value": 1540,
        "name": "NetAuthAgent.app",
        "path": "CoreServices/NetAuthAgent.app",
        "children": [
          {
            "value": 1540,
            "name": "Contents",
            "path": "CoreServices/NetAuthAgent.app/Contents"
          }
        ]
      },
      {
        "value": 3388,
        "name": "NetworkDiagnostics.app",
        "path": "CoreServices/NetworkDiagnostics.app",
        "children": [
          {
            "value": 3388,
            "name": "Contents",
            "path": "CoreServices/NetworkDiagnostics.app/Contents"
          }
        ]
      },
      {
        "value": 9384,
        "name": "NetworkSetup Assistant.app",
        "path": "CoreServices/NetworkSetup Assistant.app",
        "children": [
          {
            "value": 9384,
            "name": "Contents",
            "path": "CoreServices/NetworkSetup Assistant.app/Contents"
          }
        ]
      },
      {
        "value": 716,
        "name": "NotificationCenter.app",
        "path": "CoreServices/NotificationCenter.app",
        "children": [
          {
            "value": 716,
            "name": "Contents",
            "path": "CoreServices/NotificationCenter.app/Contents"
          }
        ]
      },
      {
        "value": 948,
        "name": "OBEXAgent.app",
        "path": "CoreServices/OBEXAgent.app",
        "children": [
          {
            "value": 948,
            "name": "Contents",
            "path": "CoreServices/OBEXAgent.app/Contents"
          }
        ]
      },
      {
        "value": 1596,
        "name": "ODSAgent.app",
        "path": "CoreServices/ODSAgent.app",
        "children": [
          {
            "value": 1596,
            "name": "Contents",
            "path": "CoreServices/ODSAgent.app/Contents"
          }
        ]
      },
      {
        "value": 492,
        "name": "PassViewer.app",
        "path": "CoreServices/PassViewer.app",
        "children": [
          {
            "value": 492,
            "name": "Contents",
            "path": "CoreServices/PassViewer.app/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "PerformanceMetricLocalizations.bundle",
        "path": "CoreServices/PerformanceMetricLocalizations.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "CoreServices/PerformanceMetricLocalizations.bundle/Contents"
          }
        ]
      },
      {
        "value": 88,
        "name": "powerd.bundle",
        "path": "CoreServices/powerd.bundle",
        "children": [
          {
            "value": 0,
            "name": "_CodeSignature",
            "path": "CoreServices/powerd.bundle/_CodeSignature"
          },
          {
            "value": 0,
            "name": "ar.lproj",
            "path": "CoreServices/powerd.bundle/ar.lproj"
          },
          {
            "value": 0,
            "name": "ca.lproj",
            "path": "CoreServices/powerd.bundle/ca.lproj"
          },
          {
            "value": 0,
            "name": "cs.lproj",
            "path": "CoreServices/powerd.bundle/cs.lproj"
          },
          {
            "value": 0,
            "name": "da.lproj",
            "path": "CoreServices/powerd.bundle/da.lproj"
          },
          {
            "value": 0,
            "name": "Dutch.lproj",
            "path": "CoreServices/powerd.bundle/Dutch.lproj"
          },
          {
            "value": 0,
            "name": "el.lproj",
            "path": "CoreServices/powerd.bundle/el.lproj"
          },
          {
            "value": 0,
            "name": "English.lproj",
            "path": "CoreServices/powerd.bundle/English.lproj"
          },
          {
            "value": 0,
            "name": "fi.lproj",
            "path": "CoreServices/powerd.bundle/fi.lproj"
          },
          {
            "value": 0,
            "name": "French.lproj",
            "path": "CoreServices/powerd.bundle/French.lproj"
          },
          {
            "value": 0,
            "name": "German.lproj",
            "path": "CoreServices/powerd.bundle/German.lproj"
          },
          {
            "value": 0,
            "name": "he.lproj",
            "path": "CoreServices/powerd.bundle/he.lproj"
          },
          {
            "value": 0,
            "name": "hr.lproj",
            "path": "CoreServices/powerd.bundle/hr.lproj"
          },
          {
            "value": 0,
            "name": "hu.lproj",
            "path": "CoreServices/powerd.bundle/hu.lproj"
          },
          {
            "value": 0,
            "name": "id.lproj",
            "path": "CoreServices/powerd.bundle/id.lproj"
          },
          {
            "value": 0,
            "name": "Italian.lproj",
            "path": "CoreServices/powerd.bundle/Italian.lproj"
          },
          {
            "value": 0,
            "name": "Japanese.lproj",
            "path": "CoreServices/powerd.bundle/Japanese.lproj"
          },
          {
            "value": 0,
            "name": "ko.lproj",
            "path": "CoreServices/powerd.bundle/ko.lproj"
          },
          {
            "value": 0,
            "name": "ms.lproj",
            "path": "CoreServices/powerd.bundle/ms.lproj"
          },
          {
            "value": 0,
            "name": "no.lproj",
            "path": "CoreServices/powerd.bundle/no.lproj"
          },
          {
            "value": 0,
            "name": "pl.lproj",
            "path": "CoreServices/powerd.bundle/pl.lproj"
          },
          {
            "value": 0,
            "name": "pt.lproj",
            "path": "CoreServices/powerd.bundle/pt.lproj"
          },
          {
            "value": 0,
            "name": "pt_PT.lproj",
            "path": "CoreServices/powerd.bundle/pt_PT.lproj"
          },
          {
            "value": 0,
            "name": "ro.lproj",
            "path": "CoreServices/powerd.bundle/ro.lproj"
          },
          {
            "value": 0,
            "name": "ru.lproj",
            "path": "CoreServices/powerd.bundle/ru.lproj"
          },
          {
            "value": 0,
            "name": "sk.lproj",
            "path": "CoreServices/powerd.bundle/sk.lproj"
          },
          {
            "value": 0,
            "name": "Spanish.lproj",
            "path": "CoreServices/powerd.bundle/Spanish.lproj"
          },
          {
            "value": 0,
            "name": "sv.lproj",
            "path": "CoreServices/powerd.bundle/sv.lproj"
          },
          {
            "value": 0,
            "name": "th.lproj",
            "path": "CoreServices/powerd.bundle/th.lproj"
          },
          {
            "value": 0,
            "name": "tr.lproj",
            "path": "CoreServices/powerd.bundle/tr.lproj"
          },
          {
            "value": 0,
            "name": "uk.lproj",
            "path": "CoreServices/powerd.bundle/uk.lproj"
          },
          {
            "value": 0,
            "name": "vi.lproj",
            "path": "CoreServices/powerd.bundle/vi.lproj"
          },
          {
            "value": 0,
            "name": "zh_CN.lproj",
            "path": "CoreServices/powerd.bundle/zh_CN.lproj"
          },
          {
            "value": 0,
            "name": "zh_TW.lproj",
            "path": "CoreServices/powerd.bundle/zh_TW.lproj"
          }
        ]
      },
      {
        "value": 776,
        "name": "ProblemReporter.app",
        "path": "CoreServices/ProblemReporter.app",
        "children": [
          {
            "value": 776,
            "name": "Contents",
            "path": "CoreServices/ProblemReporter.app/Contents"
          }
        ]
      },
      {
        "value": 4748,
        "name": "RawCamera.bundle",
        "path": "CoreServices/RawCamera.bundle",
        "children": [
          {
            "value": 4748,
            "name": "Contents",
            "path": "CoreServices/RawCamera.bundle/Contents"
          }
        ]
      },
      {
        "value": 2112,
        "name": "RawCameraSupport.bundle",
        "path": "CoreServices/RawCameraSupport.bundle",
        "children": [
          {
            "value": 2112,
            "name": "Contents",
            "path": "CoreServices/RawCameraSupport.bundle/Contents"
          }
        ]
      },
      {
        "value": 24,
        "name": "rcd.app",
        "path": "CoreServices/rcd.app",
        "children": [
          {
            "value": 24,
            "name": "Contents",
            "path": "CoreServices/rcd.app/Contents"
          }
        ]
      },
      {
        "value": 156,
        "name": "RegisterPluginIMApp.app",
        "path": "CoreServices/RegisterPluginIMApp.app",
        "children": [
          {
            "value": 156,
            "name": "Contents",
            "path": "CoreServices/RegisterPluginIMApp.app/Contents"
          }
        ]
      },
      {
        "value": 3504,
        "name": "RemoteManagement",
        "path": "CoreServices/RemoteManagement",
        "children": [
          {
            "value": 872,
            "name": "AppleVNCServer.bundle",
            "path": "CoreServices/RemoteManagement/AppleVNCServer.bundle"
          },
          {
            "value": 2260,
            "name": "ARDAgent.app",
            "path": "CoreServices/RemoteManagement/ARDAgent.app"
          },
          {
            "value": 144,
            "name": "ScreensharingAgent.bundle",
            "path": "CoreServices/RemoteManagement/ScreensharingAgent.bundle"
          },
          {
            "value": 228,
            "name": "screensharingd.bundle",
            "path": "CoreServices/RemoteManagement/screensharingd.bundle"
          }
        ]
      },
      {
        "value": 672,
        "name": "ReportPanic.app",
        "path": "CoreServices/ReportPanic.app",
        "children": [
          {
            "value": 672,
            "name": "Contents",
            "path": "CoreServices/ReportPanic.app/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "Resources",
        "path": "CoreServices/Resources",
        "children": [
          {
            "value": 0,
            "name": "ar.lproj",
            "path": "CoreServices/Resources/ar.lproj"
          },
          {
            "value": 0,
            "name": "ca.lproj",
            "path": "CoreServices/Resources/ca.lproj"
          },
          {
            "value": 0,
            "name": "cs.lproj",
            "path": "CoreServices/Resources/cs.lproj"
          },
          {
            "value": 0,
            "name": "da.lproj",
            "path": "CoreServices/Resources/da.lproj"
          },
          {
            "value": 0,
            "name": "Dutch.lproj",
            "path": "CoreServices/Resources/Dutch.lproj"
          },
          {
            "value": 0,
            "name": "el.lproj",
            "path": "CoreServices/Resources/el.lproj"
          },
          {
            "value": 0,
            "name": "English.lproj",
            "path": "CoreServices/Resources/English.lproj"
          },
          {
            "value": 0,
            "name": "fi.lproj",
            "path": "CoreServices/Resources/fi.lproj"
          },
          {
            "value": 0,
            "name": "French.lproj",
            "path": "CoreServices/Resources/French.lproj"
          },
          {
            "value": 0,
            "name": "German.lproj",
            "path": "CoreServices/Resources/German.lproj"
          },
          {
            "value": 0,
            "name": "he.lproj",
            "path": "CoreServices/Resources/he.lproj"
          },
          {
            "value": 0,
            "name": "hr.lproj",
            "path": "CoreServices/Resources/hr.lproj"
          },
          {
            "value": 0,
            "name": "hu.lproj",
            "path": "CoreServices/Resources/hu.lproj"
          },
          {
            "value": 0,
            "name": "id.lproj",
            "path": "CoreServices/Resources/id.lproj"
          },
          {
            "value": 0,
            "name": "Italian.lproj",
            "path": "CoreServices/Resources/Italian.lproj"
          },
          {
            "value": 0,
            "name": "Japanese.lproj",
            "path": "CoreServices/Resources/Japanese.lproj"
          },
          {
            "value": 0,
            "name": "ko.lproj",
            "path": "CoreServices/Resources/ko.lproj"
          },
          {
            "value": 0,
            "name": "ms.lproj",
            "path": "CoreServices/Resources/ms.lproj"
          },
          {
            "value": 0,
            "name": "no.lproj",
            "path": "CoreServices/Resources/no.lproj"
          },
          {
            "value": 0,
            "name": "pl.lproj",
            "path": "CoreServices/Resources/pl.lproj"
          },
          {
            "value": 0,
            "name": "Profiles",
            "path": "CoreServices/Resources/Profiles"
          },
          {
            "value": 0,
            "name": "pt.lproj",
            "path": "CoreServices/Resources/pt.lproj"
          },
          {
            "value": 0,
            "name": "pt_PT.lproj",
            "path": "CoreServices/Resources/pt_PT.lproj"
          },
          {
            "value": 0,
            "name": "ro.lproj",
            "path": "CoreServices/Resources/ro.lproj"
          },
          {
            "value": 0,
            "name": "ru.lproj",
            "path": "CoreServices/Resources/ru.lproj"
          },
          {
            "value": 0,
            "name": "sk.lproj",
            "path": "CoreServices/Resources/sk.lproj"
          },
          {
            "value": 0,
            "name": "Spanish.lproj",
            "path": "CoreServices/Resources/Spanish.lproj"
          },
          {
            "value": 0,
            "name": "sv.lproj",
            "path": "CoreServices/Resources/sv.lproj"
          },
          {
            "value": 0,
            "name": "th.lproj",
            "path": "CoreServices/Resources/th.lproj"
          },
          {
            "value": 0,
            "name": "tr.lproj",
            "path": "CoreServices/Resources/tr.lproj"
          },
          {
            "value": 0,
            "name": "uk.lproj",
            "path": "CoreServices/Resources/uk.lproj"
          },
          {
            "value": 0,
            "name": "vi.lproj",
            "path": "CoreServices/Resources/vi.lproj"
          },
          {
            "value": 0,
            "name": "zh_CN.lproj",
            "path": "CoreServices/Resources/zh_CN.lproj"
          },
          {
            "value": 0,
            "name": "zh_TW.lproj",
            "path": "CoreServices/Resources/zh_TW.lproj"
          }
        ]
      },
      {
        "value": 20,
        "name": "RFBEventHelper.bundle",
        "path": "CoreServices/RFBEventHelper.bundle",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "CoreServices/RFBEventHelper.bundle/Contents"
          }
        ]
      },
      {
        "value": 3304,
        "name": "ScreenSharing.app",
        "path": "CoreServices/ScreenSharing.app",
        "children": [
          {
            "value": 3304,
            "name": "Contents",
            "path": "CoreServices/ScreenSharing.app/Contents"
          }
        ]
      },
      {
        "value": 244,
        "name": "Search.bundle",
        "path": "CoreServices/Search.bundle",
        "children": [
          {
            "value": 244,
            "name": "Contents",
            "path": "CoreServices/Search.bundle/Contents"
          }
        ]
      },
      {
        "value": 4128,
        "name": "SecurityAgentPlugins",
        "path": "CoreServices/SecurityAgentPlugins",
        "children": [
          {
            "value": 304,
            "name": "DiskUnlock.bundle",
            "path": "CoreServices/SecurityAgentPlugins/DiskUnlock.bundle"
          },
          {
            "value": 1192,
            "name": "FamilyControls.bundle",
            "path": "CoreServices/SecurityAgentPlugins/FamilyControls.bundle"
          },
          {
            "value": 340,
            "name": "HomeDirMechanism.bundle",
            "path": "CoreServices/SecurityAgentPlugins/HomeDirMechanism.bundle"
          },
          {
            "value": 1156,
            "name": "KerberosAgent.bundle",
            "path": "CoreServices/SecurityAgentPlugins/KerberosAgent.bundle"
          },
          {
            "value": 276,
            "name": "loginKC.bundle",
            "path": "CoreServices/SecurityAgentPlugins/loginKC.bundle"
          },
          {
            "value": 104,
            "name": "loginwindow.bundle",
            "path": "CoreServices/SecurityAgentPlugins/loginwindow.bundle"
          },
          {
            "value": 384,
            "name": "MCXMechanism.bundle",
            "path": "CoreServices/SecurityAgentPlugins/MCXMechanism.bundle"
          },
          {
            "value": 12,
            "name": "PKINITMechanism.bundle",
            "path": "CoreServices/SecurityAgentPlugins/PKINITMechanism.bundle"
          },
          {
            "value": 360,
            "name": "RestartAuthorization.bundle",
            "path": "CoreServices/SecurityAgentPlugins/RestartAuthorization.bundle"
          }
        ]
      },
      {
        "value": 328,
        "name": "SecurityFixer.app",
        "path": "CoreServices/SecurityFixer.app",
        "children": [
          {
            "value": 328,
            "name": "Contents",
            "path": "CoreServices/SecurityFixer.app/Contents"
          }
        ]
      },
      {
        "value": 28200,
        "name": "SetupAssistant.app",
        "path": "CoreServices/SetupAssistant.app",
        "children": [
          {
            "value": 28200,
            "name": "Contents",
            "path": "CoreServices/SetupAssistant.app/Contents"
          }
        ]
      },
      {
        "value": 164,
        "name": "SetupAssistantPlugins",
        "path": "CoreServices/SetupAssistantPlugins",
        "children": [
          {
            "value": 8,
            "name": "AppStore.icdplugin",
            "path": "CoreServices/SetupAssistantPlugins/AppStore.icdplugin"
          },
          {
            "value": 8,
            "name": "Calendar.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/Calendar.flplugin"
          },
          {
            "value": 8,
            "name": "FaceTime.icdplugin",
            "path": "CoreServices/SetupAssistantPlugins/FaceTime.icdplugin"
          },
          {
            "value": 8,
            "name": "Fonts.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/Fonts.flplugin"
          },
          {
            "value": 16,
            "name": "GameCenter.icdplugin",
            "path": "CoreServices/SetupAssistantPlugins/GameCenter.icdplugin"
          },
          {
            "value": 8,
            "name": "Helpd.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/Helpd.flplugin"
          },
          {
            "value": 8,
            "name": "iBooks.icdplugin",
            "path": "CoreServices/SetupAssistantPlugins/iBooks.icdplugin"
          },
          {
            "value": 16,
            "name": "IdentityServices.icdplugin",
            "path": "CoreServices/SetupAssistantPlugins/IdentityServices.icdplugin"
          },
          {
            "value": 8,
            "name": "iMessage.icdplugin",
            "path": "CoreServices/SetupAssistantPlugins/iMessage.icdplugin"
          },
          {
            "value": 8,
            "name": "LaunchServices.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/LaunchServices.flplugin"
          },
          {
            "value": 12,
            "name": "Mail.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/Mail.flplugin"
          },
          {
            "value": 8,
            "name": "QuickLook.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/QuickLook.flplugin"
          },
          {
            "value": 8,
            "name": "Safari.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/Safari.flplugin"
          },
          {
            "value": 8,
            "name": "ServicesMenu.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/ServicesMenu.flplugin"
          },
          {
            "value": 8,
            "name": "SoftwareUpdateActions.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/SoftwareUpdateActions.flplugin"
          },
          {
            "value": 8,
            "name": "Spotlight.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/Spotlight.flplugin"
          },
          {
            "value": 16,
            "name": "UAU.flplugin",
            "path": "CoreServices/SetupAssistantPlugins/UAU.flplugin"
          }
        ]
      },
      {
        "value": 48,
        "name": "SocialPushAgent.app",
        "path": "CoreServices/SocialPushAgent.app",
        "children": [
          {
            "value": 48,
            "name": "Contents",
            "path": "CoreServices/SocialPushAgent.app/Contents"
          }
        ]
      },
      {
        "value": 2196,
        "name": "SoftwareUpdate.app",
        "path": "CoreServices/SoftwareUpdate.app",
        "children": [
          {
            "value": 2196,
            "name": "Contents",
            "path": "CoreServices/SoftwareUpdate.app/Contents"
          }
        ]
      },
      {
        "value": 856,
        "name": "Spotlight.app",
        "path": "CoreServices/Spotlight.app",
        "children": [
          {
            "value": 856,
            "name": "Contents",
            "path": "CoreServices/Spotlight.app/Contents"
          }
        ]
      },
      {
        "value": 384,
        "name": "SystemEvents.app",
        "path": "CoreServices/SystemEvents.app",
        "children": [
          {
            "value": 384,
            "name": "Contents",
            "path": "CoreServices/SystemEvents.app/Contents"
          }
        ]
      },
      {
        "value": 2152,
        "name": "SystemImage Utility.app",
        "path": "CoreServices/SystemImage Utility.app",
        "children": [
          {
            "value": 2152,
            "name": "Contents",
            "path": "CoreServices/SystemImage Utility.app/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "SystemFolderLocalizations",
        "path": "CoreServices/SystemFolderLocalizations",
        "children": [
          {
            "value": 0,
            "name": "ar.lproj",
            "path": "CoreServices/SystemFolderLocalizations/ar.lproj"
          },
          {
            "value": 0,
            "name": "ca.lproj",
            "path": "CoreServices/SystemFolderLocalizations/ca.lproj"
          },
          {
            "value": 0,
            "name": "cs.lproj",
            "path": "CoreServices/SystemFolderLocalizations/cs.lproj"
          },
          {
            "value": 0,
            "name": "da.lproj",
            "path": "CoreServices/SystemFolderLocalizations/da.lproj"
          },
          {
            "value": 0,
            "name": "de.lproj",
            "path": "CoreServices/SystemFolderLocalizations/de.lproj"
          },
          {
            "value": 0,
            "name": "el.lproj",
            "path": "CoreServices/SystemFolderLocalizations/el.lproj"
          },
          {
            "value": 0,
            "name": "en.lproj",
            "path": "CoreServices/SystemFolderLocalizations/en.lproj"
          },
          {
            "value": 0,
            "name": "es.lproj",
            "path": "CoreServices/SystemFolderLocalizations/es.lproj"
          },
          {
            "value": 0,
            "name": "fi.lproj",
            "path": "CoreServices/SystemFolderLocalizations/fi.lproj"
          },
          {
            "value": 0,
            "name": "fr.lproj",
            "path": "CoreServices/SystemFolderLocalizations/fr.lproj"
          },
          {
            "value": 0,
            "name": "he.lproj",
            "path": "CoreServices/SystemFolderLocalizations/he.lproj"
          },
          {
            "value": 0,
            "name": "hr.lproj",
            "path": "CoreServices/SystemFolderLocalizations/hr.lproj"
          },
          {
            "value": 0,
            "name": "hu.lproj",
            "path": "CoreServices/SystemFolderLocalizations/hu.lproj"
          },
          {
            "value": 0,
            "name": "id.lproj",
            "path": "CoreServices/SystemFolderLocalizations/id.lproj"
          },
          {
            "value": 0,
            "name": "it.lproj",
            "path": "CoreServices/SystemFolderLocalizations/it.lproj"
          },
          {
            "value": 0,
            "name": "ja.lproj",
            "path": "CoreServices/SystemFolderLocalizations/ja.lproj"
          },
          {
            "value": 0,
            "name": "ko.lproj",
            "path": "CoreServices/SystemFolderLocalizations/ko.lproj"
          },
          {
            "value": 0,
            "name": "ms.lproj",
            "path": "CoreServices/SystemFolderLocalizations/ms.lproj"
          },
          {
            "value": 0,
            "name": "nl.lproj",
            "path": "CoreServices/SystemFolderLocalizations/nl.lproj"
          },
          {
            "value": 0,
            "name": "no.lproj",
            "path": "CoreServices/SystemFolderLocalizations/no.lproj"
          },
          {
            "value": 0,
            "name": "pl.lproj",
            "path": "CoreServices/SystemFolderLocalizations/pl.lproj"
          },
          {
            "value": 0,
            "name": "pt.lproj",
            "path": "CoreServices/SystemFolderLocalizations/pt.lproj"
          },
          {
            "value": 0,
            "name": "pt_PT.lproj",
            "path": "CoreServices/SystemFolderLocalizations/pt_PT.lproj"
          },
          {
            "value": 0,
            "name": "ro.lproj",
            "path": "CoreServices/SystemFolderLocalizations/ro.lproj"
          },
          {
            "value": 0,
            "name": "ru.lproj",
            "path": "CoreServices/SystemFolderLocalizations/ru.lproj"
          },
          {
            "value": 0,
            "name": "sk.lproj",
            "path": "CoreServices/SystemFolderLocalizations/sk.lproj"
          },
          {
            "value": 0,
            "name": "sv.lproj",
            "path": "CoreServices/SystemFolderLocalizations/sv.lproj"
          },
          {
            "value": 0,
            "name": "th.lproj",
            "path": "CoreServices/SystemFolderLocalizations/th.lproj"
          },
          {
            "value": 0,
            "name": "tr.lproj",
            "path": "CoreServices/SystemFolderLocalizations/tr.lproj"
          },
          {
            "value": 0,
            "name": "uk.lproj",
            "path": "CoreServices/SystemFolderLocalizations/uk.lproj"
          },
          {
            "value": 0,
            "name": "vi.lproj",
            "path": "CoreServices/SystemFolderLocalizations/vi.lproj"
          },
          {
            "value": 0,
            "name": "zh_CN.lproj",
            "path": "CoreServices/SystemFolderLocalizations/zh_CN.lproj"
          },
          {
            "value": 0,
            "name": "zh_TW.lproj",
            "path": "CoreServices/SystemFolderLocalizations/zh_TW.lproj"
          }
        ]
      },
      {
        "value": 852,
        "name": "SystemUIServer.app",
        "path": "CoreServices/SystemUIServer.app",
        "children": [
          {
            "value": 852,
            "name": "Contents",
            "path": "CoreServices/SystemUIServer.app/Contents"
          }
        ]
      },
      {
        "value": 132,
        "name": "SystemVersion.bundle",
        "path": "CoreServices/SystemVersion.bundle",
        "children": [
          {
            "value": 4,
            "name": "ar.lproj",
            "path": "CoreServices/SystemVersion.bundle/ar.lproj"
          },
          {
            "value": 4,
            "name": "ca.lproj",
            "path": "CoreServices/SystemVersion.bundle/ca.lproj"
          },
          {
            "value": 4,
            "name": "cs.lproj",
            "path": "CoreServices/SystemVersion.bundle/cs.lproj"
          },
          {
            "value": 4,
            "name": "da.lproj",
            "path": "CoreServices/SystemVersion.bundle/da.lproj"
          },
          {
            "value": 4,
            "name": "Dutch.lproj",
            "path": "CoreServices/SystemVersion.bundle/Dutch.lproj"
          },
          {
            "value": 4,
            "name": "el.lproj",
            "path": "CoreServices/SystemVersion.bundle/el.lproj"
          },
          {
            "value": 4,
            "name": "English.lproj",
            "path": "CoreServices/SystemVersion.bundle/English.lproj"
          },
          {
            "value": 4,
            "name": "fi.lproj",
            "path": "CoreServices/SystemVersion.bundle/fi.lproj"
          },
          {
            "value": 4,
            "name": "French.lproj",
            "path": "CoreServices/SystemVersion.bundle/French.lproj"
          },
          {
            "value": 4,
            "name": "German.lproj",
            "path": "CoreServices/SystemVersion.bundle/German.lproj"
          },
          {
            "value": 4,
            "name": "he.lproj",
            "path": "CoreServices/SystemVersion.bundle/he.lproj"
          },
          {
            "value": 4,
            "name": "hr.lproj",
            "path": "CoreServices/SystemVersion.bundle/hr.lproj"
          },
          {
            "value": 4,
            "name": "hu.lproj",
            "path": "CoreServices/SystemVersion.bundle/hu.lproj"
          },
          {
            "value": 4,
            "name": "id.lproj",
            "path": "CoreServices/SystemVersion.bundle/id.lproj"
          },
          {
            "value": 4,
            "name": "Italian.lproj",
            "path": "CoreServices/SystemVersion.bundle/Italian.lproj"
          },
          {
            "value": 4,
            "name": "Japanese.lproj",
            "path": "CoreServices/SystemVersion.bundle/Japanese.lproj"
          },
          {
            "value": 4,
            "name": "ko.lproj",
            "path": "CoreServices/SystemVersion.bundle/ko.lproj"
          },
          {
            "value": 4,
            "name": "ms.lproj",
            "path": "CoreServices/SystemVersion.bundle/ms.lproj"
          },
          {
            "value": 4,
            "name": "no.lproj",
            "path": "CoreServices/SystemVersion.bundle/no.lproj"
          },
          {
            "value": 4,
            "name": "pl.lproj",
            "path": "CoreServices/SystemVersion.bundle/pl.lproj"
          },
          {
            "value": 4,
            "name": "pt.lproj",
            "path": "CoreServices/SystemVersion.bundle/pt.lproj"
          },
          {
            "value": 4,
            "name": "pt_PT.lproj",
            "path": "CoreServices/SystemVersion.bundle/pt_PT.lproj"
          },
          {
            "value": 4,
            "name": "ro.lproj",
            "path": "CoreServices/SystemVersion.bundle/ro.lproj"
          },
          {
            "value": 4,
            "name": "ru.lproj",
            "path": "CoreServices/SystemVersion.bundle/ru.lproj"
          },
          {
            "value": 4,
            "name": "sk.lproj",
            "path": "CoreServices/SystemVersion.bundle/sk.lproj"
          },
          {
            "value": 4,
            "name": "Spanish.lproj",
            "path": "CoreServices/SystemVersion.bundle/Spanish.lproj"
          },
          {
            "value": 4,
            "name": "sv.lproj",
            "path": "CoreServices/SystemVersion.bundle/sv.lproj"
          },
          {
            "value": 4,
            "name": "th.lproj",
            "path": "CoreServices/SystemVersion.bundle/th.lproj"
          },
          {
            "value": 4,
            "name": "tr.lproj",
            "path": "CoreServices/SystemVersion.bundle/tr.lproj"
          },
          {
            "value": 4,
            "name": "uk.lproj",
            "path": "CoreServices/SystemVersion.bundle/uk.lproj"
          },
          {
            "value": 4,
            "name": "vi.lproj",
            "path": "CoreServices/SystemVersion.bundle/vi.lproj"
          },
          {
            "value": 4,
            "name": "zh_CN.lproj",
            "path": "CoreServices/SystemVersion.bundle/zh_CN.lproj"
          },
          {
            "value": 4,
            "name": "zh_TW.lproj",
            "path": "CoreServices/SystemVersion.bundle/zh_TW.lproj"
          }
        ]
      },
      {
        "value": 3148,
        "name": "TicketViewer.app",
        "path": "CoreServices/TicketViewer.app",
        "children": [
          {
            "value": 3148,
            "name": "Contents",
            "path": "CoreServices/TicketViewer.app/Contents"
          }
        ]
      },
      {
        "value": 532,
        "name": "TypographyPanel.bundle",
        "path": "CoreServices/TypographyPanel.bundle",
        "children": [
          {
            "value": 532,
            "name": "Contents",
            "path": "CoreServices/TypographyPanel.bundle/Contents"
          }
        ]
      },
      {
        "value": 676,
        "name": "UniversalAccessControl.app",
        "path": "CoreServices/UniversalAccessControl.app",
        "children": [
          {
            "value": 676,
            "name": "Contents",
            "path": "CoreServices/UniversalAccessControl.app/Contents"
          }
        ]
      },
      {
        "value": 52,
        "name": "UnmountAssistantAgent.app",
        "path": "CoreServices/UnmountAssistantAgent.app",
        "children": [
          {
            "value": 52,
            "name": "Contents",
            "path": "CoreServices/UnmountAssistantAgent.app/Contents"
          }
        ]
      },
      {
        "value": 60,
        "name": "UserNotificationCenter.app",
        "path": "CoreServices/UserNotificationCenter.app",
        "children": [
          {
            "value": 60,
            "name": "Contents",
            "path": "CoreServices/UserNotificationCenter.app/Contents"
          }
        ]
      },
      {
        "value": 456,
        "name": "VoiceOver.app",
        "path": "CoreServices/VoiceOver.app",
        "children": [
          {
            "value": 456,
            "name": "Contents",
            "path": "CoreServices/VoiceOver.app/Contents"
          }
        ]
      },
      {
        "value": 44,
        "name": "XsanManagerDaemon.bundle",
        "path": "CoreServices/XsanManagerDaemon.bundle",
        "children": [
          {
            "value": 44,
            "name": "Contents",
            "path": "CoreServices/XsanManagerDaemon.bundle/Contents"
          }
        ]
      },
      {
        "value": 844,
        "name": "ZoomWindow.app",
        "path": "CoreServices/ZoomWindow.app",
        "children": [
          {
            "value": 844,
            "name": "Contents",
            "path": "CoreServices/ZoomWindow.app/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 72,
    "name": "DirectoryServices",
    "path": "DirectoryServices",
    "children": [
      {
        "value": 0,
        "name": "DefaultLocalDB",
        "path": "DirectoryServices/DefaultLocalDB"
      },
      {
        "value": 72,
        "name": "dscl",
        "path": "DirectoryServices/dscl",
        "children": [
          {
            "value": 44,
            "name": "mcxcl.dsclext",
            "path": "DirectoryServices/dscl/mcxcl.dsclext"
          },
          {
            "value": 28,
            "name": "mcxProfiles.dsclext",
            "path": "DirectoryServices/dscl/mcxProfiles.dsclext"
          }
        ]
      },
      {
        "value": 0,
        "name": "Templates",
        "path": "DirectoryServices/Templates",
        "children": [
          {
            "value": 0,
            "name": "LDAPv3",
            "path": "DirectoryServices/Templates/LDAPv3"
          }
        ]
      }
    ]
  },
  {
    "value": 0,
    "name": "Displays",
    "path": "Displays",
    "children": [
      {
        "value": 0,
        "name": "_CodeSignature",
        "path": "Displays/_CodeSignature"
      },
      {
        "value": 0,
        "name": "Overrides",
        "path": "Displays/Overrides",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "Displays/Overrides/Contents"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-11a9",
            "path": "Displays/Overrides/DisplayVendorID-11a9"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-2283",
            "path": "Displays/Overrides/DisplayVendorID-2283"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-34a9",
            "path": "Displays/Overrides/DisplayVendorID-34a9"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-38a3",
            "path": "Displays/Overrides/DisplayVendorID-38a3"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-4c2d",
            "path": "Displays/Overrides/DisplayVendorID-4c2d"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-4dd9",
            "path": "Displays/Overrides/DisplayVendorID-4dd9"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-5a63",
            "path": "Displays/Overrides/DisplayVendorID-5a63"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-5b4",
            "path": "Displays/Overrides/DisplayVendorID-5b4"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-610",
            "path": "Displays/Overrides/DisplayVendorID-610"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-756e6b6e",
            "path": "Displays/Overrides/DisplayVendorID-756e6b6e"
          },
          {
            "value": 0,
            "name": "DisplayVendorID-daf",
            "path": "Displays/Overrides/DisplayVendorID-daf"
          }
        ]
      }
    ]
  },
  {
    "value": 16,
    "name": "DTDs",
    "path": "DTDs"
  },
  {
    "value": 400116,
    "name": "Extensions",
    "path": "Extensions",
    "children": [
      {
        "value": 0,
        "name": "10.5",
        "path": "Extensions/10.5"
      },
      {
        "value": 0,
        "name": "10.6",
        "path": "Extensions/10.6"
      },
      {
        "value": 116,
        "name": "Accusys6xxxx.kext",
        "path": "Extensions/Accusys6xxxx.kext",
        "children": [
          {
            "value": 116,
            "name": "Contents",
            "path": "Extensions/Accusys6xxxx.kext/Contents"
          }
        ]
      },
      {
        "value": 1236,
        "name": "acfs.kext",
        "path": "Extensions/acfs.kext",
        "children": [
          {
            "value": 1236,
            "name": "Contents",
            "path": "Extensions/acfs.kext/Contents"
          }
        ]
      },
      {
        "value": 32,
        "name": "acfsctl.kext",
        "path": "Extensions/acfsctl.kext",
        "children": [
          {
            "value": 32,
            "name": "Contents",
            "path": "Extensions/acfsctl.kext/Contents"
          }
        ]
      },
      {
        "value": 196,
        "name": "ALF.kext",
        "path": "Extensions/ALF.kext",
        "children": [
          {
            "value": 196,
            "name": "Contents",
            "path": "Extensions/ALF.kext/Contents"
          }
        ]
      },
      {
        "value": 1836,
        "name": "AMD2400Controller.kext",
        "path": "Extensions/AMD2400Controller.kext",
        "children": [
          {
            "value": 1836,
            "name": "Contents",
            "path": "Extensions/AMD2400Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 1840,
        "name": "AMD2600Controller.kext",
        "path": "Extensions/AMD2600Controller.kext",
        "children": [
          {
            "value": 1840,
            "name": "Contents",
            "path": "Extensions/AMD2600Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 1848,
        "name": "AMD3800Controller.kext",
        "path": "Extensions/AMD3800Controller.kext",
        "children": [
          {
            "value": 1848,
            "name": "Contents",
            "path": "Extensions/AMD3800Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 1828,
        "name": "AMD4600Controller.kext",
        "path": "Extensions/AMD4600Controller.kext",
        "children": [
          {
            "value": 1828,
            "name": "Contents",
            "path": "Extensions/AMD4600Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 1820,
        "name": "AMD4800Controller.kext",
        "path": "Extensions/AMD4800Controller.kext",
        "children": [
          {
            "value": 1820,
            "name": "Contents",
            "path": "Extensions/AMD4800Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 2268,
        "name": "AMD5000Controller.kext",
        "path": "Extensions/AMD5000Controller.kext",
        "children": [
          {
            "value": 2268,
            "name": "Contents",
            "path": "Extensions/AMD5000Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 2292,
        "name": "AMD6000Controller.kext",
        "path": "Extensions/AMD6000Controller.kext",
        "children": [
          {
            "value": 2292,
            "name": "Contents",
            "path": "Extensions/AMD6000Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 2316,
        "name": "AMD7000Controller.kext",
        "path": "Extensions/AMD7000Controller.kext",
        "children": [
          {
            "value": 2316,
            "name": "Contents",
            "path": "Extensions/AMD7000Controller.kext/Contents"
          }
        ]
      },
      {
        "value": 164,
        "name": "AMDFramebuffer.kext",
        "path": "Extensions/AMDFramebuffer.kext",
        "children": [
          {
            "value": 164,
            "name": "Contents",
            "path": "Extensions/AMDFramebuffer.kext/Contents"
          }
        ]
      },
      {
        "value": 1572,
        "name": "AMDRadeonVADriver.bundle",
        "path": "Extensions/AMDRadeonVADriver.bundle",
        "children": [
          {
            "value": 1572,
            "name": "Contents",
            "path": "Extensions/AMDRadeonVADriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 4756,
        "name": "AMDRadeonX3000.kext",
        "path": "Extensions/AMDRadeonX3000.kext",
        "children": [
          {
            "value": 4756,
            "name": "Contents",
            "path": "Extensions/AMDRadeonX3000.kext/Contents"
          }
        ]
      },
      {
        "value": 11224,
        "name": "AMDRadeonX3000GLDriver.bundle",
        "path": "Extensions/AMDRadeonX3000GLDriver.bundle",
        "children": [
          {
            "value": 11224,
            "name": "Contents",
            "path": "Extensions/AMDRadeonX3000GLDriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 4532,
        "name": "AMDRadeonX4000.kext",
        "path": "Extensions/AMDRadeonX4000.kext",
        "children": [
          {
            "value": 4532,
            "name": "Contents",
            "path": "Extensions/AMDRadeonX4000.kext/Contents"
          }
        ]
      },
      {
        "value": 17144,
        "name": "AMDRadeonX4000GLDriver.bundle",
        "path": "Extensions/AMDRadeonX4000GLDriver.bundle",
        "children": [
          {
            "value": 17144,
            "name": "Contents",
            "path": "Extensions/AMDRadeonX4000GLDriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 544,
        "name": "AMDSupport.kext",
        "path": "Extensions/AMDSupport.kext",
        "children": [
          {
            "value": 544,
            "name": "Contents",
            "path": "Extensions/AMDSupport.kext/Contents"
          }
        ]
      },
      {
        "value": 148,
        "name": "Apple16X50Serial.kext",
        "path": "Extensions/Apple16X50Serial.kext",
        "children": [
          {
            "value": 148,
            "name": "Contents",
            "path": "Extensions/Apple16X50Serial.kext/Contents"
          }
        ]
      },
      {
        "value": 60,
        "name": "Apple_iSight.kext",
        "path": "Extensions/Apple_iSight.kext",
        "children": [
          {
            "value": 60,
            "name": "Contents",
            "path": "Extensions/Apple_iSight.kext/Contents"
          }
        ]
      },
      {
        "value": 596,
        "name": "AppleACPIPlatform.kext",
        "path": "Extensions/AppleACPIPlatform.kext",
        "children": [
          {
            "value": 596,
            "name": "Contents",
            "path": "Extensions/AppleACPIPlatform.kext/Contents"
          }
        ]
      },
      {
        "value": 208,
        "name": "AppleAHCIPort.kext",
        "path": "Extensions/AppleAHCIPort.kext",
        "children": [
          {
            "value": 208,
            "name": "Contents",
            "path": "Extensions/AppleAHCIPort.kext/Contents"
          }
        ]
      },
      {
        "value": 56,
        "name": "AppleAPIC.kext",
        "path": "Extensions/AppleAPIC.kext",
        "children": [
          {
            "value": 56,
            "name": "Contents",
            "path": "Extensions/AppleAPIC.kext/Contents"
          }
        ]
      },
      {
        "value": 84,
        "name": "AppleBacklight.kext",
        "path": "Extensions/AppleBacklight.kext",
        "children": [
          {
            "value": 84,
            "name": "Contents",
            "path": "Extensions/AppleBacklight.kext/Contents"
          }
        ]
      },
      {
        "value": 56,
        "name": "AppleBacklightExpert.kext",
        "path": "Extensions/AppleBacklightExpert.kext",
        "children": [
          {
            "value": 4,
            "name": "_CodeSignature",
            "path": "Extensions/AppleBacklightExpert.kext/_CodeSignature"
          }
        ]
      },
      {
        "value": 180,
        "name": "AppleBluetoothMultitouch.kext",
        "path": "Extensions/AppleBluetoothMultitouch.kext",
        "children": [
          {
            "value": 180,
            "name": "Contents",
            "path": "Extensions/AppleBluetoothMultitouch.kext/Contents"
          }
        ]
      },
      {
        "value": 80,
        "name": "AppleBMC.kext",
        "path": "Extensions/AppleBMC.kext",
        "children": [
          {
            "value": 80,
            "name": "Contents",
            "path": "Extensions/AppleBMC.kext/Contents"
          }
        ]
      },
      {
        "value": 152,
        "name": "AppleCameraInterface.kext",
        "path": "Extensions/AppleCameraInterface.kext",
        "children": [
          {
            "value": 152,
            "name": "Contents",
            "path": "Extensions/AppleCameraInterface.kext/Contents"
          }
        ]
      },
      {
        "value": 152,
        "name": "AppleEFIRuntime.kext",
        "path": "Extensions/AppleEFIRuntime.kext",
        "children": [
          {
            "value": 152,
            "name": "Contents",
            "path": "Extensions/AppleEFIRuntime.kext/Contents"
          }
        ]
      },
      {
        "value": 88,
        "name": "AppleFDEKeyStore.kext",
        "path": "Extensions/AppleFDEKeyStore.kext",
        "children": [
          {
            "value": 88,
            "name": "Contents",
            "path": "Extensions/AppleFDEKeyStore.kext/Contents"
          }
        ]
      },
      {
        "value": 48,
        "name": "AppleFileSystemDriver.kext",
        "path": "Extensions/AppleFileSystemDriver.kext",
        "children": [
          {
            "value": 48,
            "name": "Contents",
            "path": "Extensions/AppleFileSystemDriver.kext/Contents"
          }
        ]
      },
      {
        "value": 56,
        "name": "AppleFSCompressionTypeDataless.kext",
        "path": "Extensions/AppleFSCompressionTypeDataless.kext",
        "children": [
          {
            "value": 56,
            "name": "Contents",
            "path": "Extensions/AppleFSCompressionTypeDataless.kext/Contents"
          }
        ]
      },
      {
        "value": 60,
        "name": "AppleFSCompressionTypeZlib.kext",
        "path": "Extensions/AppleFSCompressionTypeZlib.kext",
        "children": [
          {
            "value": 60,
            "name": "Contents",
            "path": "Extensions/AppleFSCompressionTypeZlib.kext/Contents"
          }
        ]
      },
      {
        "value": 628,
        "name": "AppleFWAudio.kext",
        "path": "Extensions/AppleFWAudio.kext",
        "children": [
          {
            "value": 628,
            "name": "Contents",
            "path": "Extensions/AppleFWAudio.kext/Contents"
          }
        ]
      },
      {
        "value": 396,
        "name": "AppleGraphicsControl.kext",
        "path": "Extensions/AppleGraphicsControl.kext",
        "children": [
          {
            "value": 396,
            "name": "Contents",
            "path": "Extensions/AppleGraphicsControl.kext/Contents"
          }
        ]
      },
      {
        "value": 276,
        "name": "AppleGraphicsPowerManagement.kext",
        "path": "Extensions/AppleGraphicsPowerManagement.kext",
        "children": [
          {
            "value": 276,
            "name": "Contents",
            "path": "Extensions/AppleGraphicsPowerManagement.kext/Contents"
          }
        ]
      },
      {
        "value": 3112,
        "name": "AppleHDA.kext",
        "path": "Extensions/AppleHDA.kext",
        "children": [
          {
            "value": 3112,
            "name": "Contents",
            "path": "Extensions/AppleHDA.kext/Contents"
          }
        ]
      },
      {
        "value": 488,
        "name": "AppleHIDKeyboard.kext",
        "path": "Extensions/AppleHIDKeyboard.kext",
        "children": [
          {
            "value": 488,
            "name": "Contents",
            "path": "Extensions/AppleHIDKeyboard.kext/Contents"
          }
        ]
      },
      {
        "value": 184,
        "name": "AppleHIDMouse.kext",
        "path": "Extensions/AppleHIDMouse.kext",
        "children": [
          {
            "value": 184,
            "name": "Contents",
            "path": "Extensions/AppleHIDMouse.kext/Contents"
          }
        ]
      },
      {
        "value": 52,
        "name": "AppleHPET.kext",
        "path": "Extensions/AppleHPET.kext",
        "children": [
          {
            "value": 52,
            "name": "Contents",
            "path": "Extensions/AppleHPET.kext/Contents"
          }
        ]
      },
      {
        "value": 64,
        "name": "AppleHSSPIHIDDriver.kext",
        "path": "Extensions/AppleHSSPIHIDDriver.kext",
        "children": [
          {
            "value": 64,
            "name": "Contents",
            "path": "Extensions/AppleHSSPIHIDDriver.kext/Contents"
          }
        ]
      },
      {
        "value": 144,
        "name": "AppleHSSPISupport.kext",
        "path": "Extensions/AppleHSSPISupport.kext",
        "children": [
          {
            "value": 144,
            "name": "Contents",
            "path": "Extensions/AppleHSSPISupport.kext/Contents"
          }
        ]
      },
      {
        "value": 64,
        "name": "AppleHWAccess.kext",
        "path": "Extensions/AppleHWAccess.kext",
        "children": [
          {
            "value": 64,
            "name": "Contents",
            "path": "Extensions/AppleHWAccess.kext/Contents"
          }
        ]
      },
      {
        "value": 72,
        "name": "AppleHWSensor.kext",
        "path": "Extensions/AppleHWSensor.kext",
        "children": [
          {
            "value": 72,
            "name": "Contents",
            "path": "Extensions/AppleHWSensor.kext/Contents"
          }
        ]
      },
      {
        "value": 244,
        "name": "AppleIntelCPUPowerManagement.kext",
        "path": "Extensions/AppleIntelCPUPowerManagement.kext",
        "children": [
          {
            "value": 244,
            "name": "Contents",
            "path": "Extensions/AppleIntelCPUPowerManagement.kext/Contents"
          }
        ]
      },
      {
        "value": 52,
        "name": "AppleIntelCPUPowerManagementClient.kext",
        "path": "Extensions/AppleIntelCPUPowerManagementClient.kext",
        "children": [
          {
            "value": 52,
            "name": "Contents",
            "path": "Extensions/AppleIntelCPUPowerManagementClient.kext/Contents"
          }
        ]
      },
      {
        "value": 480,
        "name": "AppleIntelFramebufferAzul.kext",
        "path": "Extensions/AppleIntelFramebufferAzul.kext",
        "children": [
          {
            "value": 480,
            "name": "Contents",
            "path": "Extensions/AppleIntelFramebufferAzul.kext/Contents"
          }
        ]
      },
      {
        "value": 492,
        "name": "AppleIntelFramebufferCapri.kext",
        "path": "Extensions/AppleIntelFramebufferCapri.kext",
        "children": [
          {
            "value": 492,
            "name": "Contents",
            "path": "Extensions/AppleIntelFramebufferCapri.kext/Contents"
          }
        ]
      },
      {
        "value": 604,
        "name": "AppleIntelHD3000Graphics.kext",
        "path": "Extensions/AppleIntelHD3000Graphics.kext",
        "children": [
          {
            "value": 604,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD3000Graphics.kext/Contents"
          }
        ]
      },
      {
        "value": 64,
        "name": "AppleIntelHD3000GraphicsGA.plugin",
        "path": "Extensions/AppleIntelHD3000GraphicsGA.plugin",
        "children": [
          {
            "value": 64,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD3000GraphicsGA.plugin/Contents"
          }
        ]
      },
      {
        "value": 9164,
        "name": "AppleIntelHD3000GraphicsGLDriver.bundle",
        "path": "Extensions/AppleIntelHD3000GraphicsGLDriver.bundle",
        "children": [
          {
            "value": 9164,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD3000GraphicsGLDriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 2520,
        "name": "AppleIntelHD3000GraphicsVADriver.bundle",
        "path": "Extensions/AppleIntelHD3000GraphicsVADriver.bundle",
        "children": [
          {
            "value": 2520,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD3000GraphicsVADriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 536,
        "name": "AppleIntelHD4000Graphics.kext",
        "path": "Extensions/AppleIntelHD4000Graphics.kext",
        "children": [
          {
            "value": 536,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD4000Graphics.kext/Contents"
          }
        ]
      },
      {
        "value": 22996,
        "name": "AppleIntelHD4000GraphicsGLDriver.bundle",
        "path": "Extensions/AppleIntelHD4000GraphicsGLDriver.bundle",
        "children": [
          {
            "value": 22996,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD4000GraphicsGLDriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 3608,
        "name": "AppleIntelHD4000GraphicsVADriver.bundle",
        "path": "Extensions/AppleIntelHD4000GraphicsVADriver.bundle",
        "children": [
          {
            "value": 3608,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD4000GraphicsVADriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 564,
        "name": "AppleIntelHD5000Graphics.kext",
        "path": "Extensions/AppleIntelHD5000Graphics.kext",
        "children": [
          {
            "value": 564,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD5000Graphics.kext/Contents"
          }
        ]
      },
      {
        "value": 20692,
        "name": "AppleIntelHD5000GraphicsGLDriver.bundle",
        "path": "Extensions/AppleIntelHD5000GraphicsGLDriver.bundle",
        "children": [
          {
            "value": 20692,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD5000GraphicsGLDriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 6120,
        "name": "AppleIntelHD5000GraphicsVADriver.bundle",
        "path": "Extensions/AppleIntelHD5000GraphicsVADriver.bundle",
        "children": [
          {
            "value": 6120,
            "name": "Contents",
            "path": "Extensions/AppleIntelHD5000GraphicsVADriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 976,
        "name": "AppleIntelHDGraphics.kext",
        "path": "Extensions/AppleIntelHDGraphics.kext",
        "children": [
          {
            "value": 976,
            "name": "Contents",
            "path": "Extensions/AppleIntelHDGraphics.kext/Contents"
          }
        ]
      },
      {
        "value": 148,
        "name": "AppleIntelHDGraphicsFB.kext",
        "path": "Extensions/AppleIntelHDGraphicsFB.kext",
        "children": [
          {
            "value": 148,
            "name": "Contents",
            "path": "Extensions/AppleIntelHDGraphicsFB.kext/Contents"
          }
        ]
      },
      {
        "value": 64,
        "name": "AppleIntelHDGraphicsGA.plugin",
        "path": "Extensions/AppleIntelHDGraphicsGA.plugin",
        "children": [
          {
            "value": 64,
            "name": "Contents",
            "path": "Extensions/AppleIntelHDGraphicsGA.plugin/Contents"
          }
        ]
      },
      {
        "value": 9108,
        "name": "AppleIntelHDGraphicsGLDriver.bundle",
        "path": "Extensions/AppleIntelHDGraphicsGLDriver.bundle",
        "children": [
          {
            "value": 9108,
            "name": "Contents",
            "path": "Extensions/AppleIntelHDGraphicsGLDriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 104,
        "name": "AppleIntelHDGraphicsVADriver.bundle",
        "path": "Extensions/AppleIntelHDGraphicsVADriver.bundle",
        "children": [
          {
            "value": 104,
            "name": "Contents",
            "path": "Extensions/AppleIntelHDGraphicsVADriver.bundle/Contents"
          }
        ]
      },
      {
        "value": 96,
        "name": "AppleIntelHSWVA.bundle",
        "path": "Extensions/AppleIntelHSWVA.bundle",
        "children": [
          {
            "value": 96,
            "name": "Contents",
            "path": "Extensions/AppleIntelHSWVA.bundle/Contents"
          }
        ]
      },
      {
        "value": 96,
        "name": "AppleIntelIVBVA.bundle",
        "path": "Extensions/AppleIntelIVBVA.bundle",
        "children": [
          {
            "value": 96,
            "name": "Contents",
            "path": "Extensions/AppleIntelIVBVA.bundle/Contents"
          }
        ]
      },
      {
        "value": 72,
        "name": "AppleIntelLpssDmac.kext",
        "path": "Extensions/AppleIntelLpssDmac.kext",
        "children": [
          {
            "value": 72,
            "name": "Contents",
            "path": "Extensions/AppleIntelLpssDmac.kext/Contents"
          }
        ]
      },
      {
        "value": 76,
        "name": "AppleIntelLpssGspi.kext",
        "path": "Extensions/AppleIntelLpssGspi.kext",
        "children": [
          {
            "value": 76,
            "name": "Contents",
            "path": "Extensions/AppleIntelLpssGspi.kext/Contents"
          }
        ]
      },
      {
        "value": 132,
        "name": "AppleIntelLpssSpiController.kext",
        "path": "Extensions/AppleIntelLpssSpiController.kext",
        "children": [
          {
            "value": 132,
            "name": "Contents",
            "path": "Extensions/AppleIntelLpssSpiController.kext/Contents"
          }
        ]
      },
      {
        "value": 308,
        "name": "AppleIntelSNBGraphicsFB.kext",
        "path": "Extensions/AppleIntelSNBGraphicsFB.kext",
        "children": [
          {
            "value": 308,
            "name": "Contents",
            "path": "Extensions/AppleIntelSNBGraphicsFB.kext/Contents"
          }
        ]
      },
      {
        "value": 144,
        "name": "AppleIntelSNBVA.bundle",
        "path": "Extensions/AppleIntelSNBVA.bundle",
        "children": [
          {
            "value": 144,
            "name": "Contents",
            "path": "Extensions/AppleIntelSNBVA.bundle/Contents"
          }
        ]
      },
      {
        "value": 72,
        "name": "AppleIRController.kext",
        "path": "Extensions/AppleIRController.kext",
        "children": [
          {
            "value": 72,
            "name": "Contents",
            "path": "Extensions/AppleIRController.kext/Contents"
          }
        ]
      },
      {
        "value": 208,
        "name": "AppleKextExcludeList.kext",
        "path": "Extensions/AppleKextExcludeList.kext",
        "children": [
          {
            "value": 208,
            "name": "Contents",
            "path": "Extensions/AppleKextExcludeList.kext/Contents"
          }
        ]
      },
      {
        "value": 120,
        "name": "AppleKeyStore.kext",
        "path": "Extensions/AppleKeyStore.kext",
        "children": [
          {
            "value": 120,
            "name": "Contents",
            "path": "Extensions/AppleKeyStore.kext/Contents"
          }
        ]
      },
      {
        "value": 48,
        "name": "AppleKeyswitch.kext",
        "path": "Extensions/AppleKeyswitch.kext",
        "children": [
          {
            "value": 48,
            "name": "Contents",
            "path": "Extensions/AppleKeyswitch.kext/Contents"
          }
        ]
      },
      {
        "value": 56,
        "name": "AppleLPC.kext",
        "path": "Extensions/AppleLPC.kext",
        "children": [
          {
            "value": 56,
            "name": "Contents",
            "path": "Extensions/AppleLPC.kext/Contents"
          }
        ]
      },
      {
        "value": 188,
        "name": "AppleLSIFusionMPT.kext",
        "path": "Extensions/AppleLSIFusionMPT.kext",
        "children": [
          {
            "value": 188,
            "name": "Contents",
            "path": "Extensions/AppleLSIFusionMPT.kext/Contents"
          }
        ]
      },
      {
        "value": 36,
        "name": "AppleMatch.kext",
        "path": "Extensions/AppleMatch.kext",
        "children": [
          {
            "value": 36,
            "name": "Contents",
            "path": "Extensions/AppleMatch.kext/Contents"
          }
        ]
      },
      {
        "value": 140,
        "name": "AppleMCCSControl.kext",
        "path": "Extensions/AppleMCCSControl.kext",
        "children": [
          {
            "value": 140,
            "name": "Contents",
            "path": "Extensions/AppleMCCSControl.kext/Contents"
          }
        ]
      },
      {
        "value": 64,
        "name": "AppleMCEDriver.kext",
        "path": "Extensions/AppleMCEDriver.kext",
        "children": [
          {
            "value": 64,
            "name": "Contents",
            "path": "Extensions/AppleMCEDriver.kext/Contents"
          }
        ]
      },
      {
        "value": 76,
        "name": "AppleMCP89RootPortPM.kext",
        "path": "Extensions/AppleMCP89RootPortPM.kext",
        "children": [
          {
            "value": 76,
            "name": "Contents",
            "path": "Extensions/AppleMCP89RootPortPM.kext/Contents"
          }
        ]
      },
      {
        "value": 156,
        "name": "AppleMIDIFWDriver.plugin",
        "path": "Extensions/AppleMIDIFWDriver.plugin",
        "children": [
          {
            "value": 156,
            "name": "Contents",
            "path": "Extensions/AppleMIDIFWDriver.plugin/Contents"
          }
        ]
      },
      {
        "value": 236,
        "name": "AppleMIDIIACDriver.plugin",
        "path": "Extensions/AppleMIDIIACDriver.plugin",
        "children": [
          {
            "value": 236,
            "name": "Contents",
            "path": "Extensions/AppleMIDIIACDriver.plugin/Contents"
          }
        ]
      },
      {
        "value": 416,
        "name": "AppleMIDIRTPDriver.plugin",
        "path": "Extensions/AppleMIDIRTPDriver.plugin",
        "children": [
          {
            "value": 416,
            "name": "Contents",
            "path": "Extensions/AppleMIDIRTPDriver.plugin/Contents"
          }
        ]
      },
      {
        "value": 248,
        "name": "AppleMIDIUSBDriver.plugin",
        "path": "Extensions/AppleMIDIUSBDriver.plugin",
        "children": [
          {
            "value": 248,
            "name": "Contents",
            "path": "Extensions/AppleMIDIUSBDriver.plugin/Contents"
          }
        ]
      },
      {
        "value": 68,
        "name": "AppleMikeyHIDDriver.kext",
        "path": "Extensions/AppleMikeyHIDDriver.kext",
        "children": [
          {
            "value": 68,
            "name": "Contents",
            "path": "Extensions/AppleMikeyHIDDriver.kext/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "AppleMobileDevice.kext",
        "path": "Extensions/AppleMobileDevice.kext",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "Extensions/AppleMobileDevice.kext/Contents"
          }
        ]
      },
      {
        "value": 860,
        "name": "AppleMultitouchDriver.kext",
        "path": "Extensions/AppleMultitouchDriver.kext",
        "children": [
          {
            "value": 860,
            "name": "Contents",
            "path": "Extensions/AppleMultitouchDriver.kext/Contents"
          }
        ]
      },
      {
        "value": 136,
        "name": "ApplePlatformEnabler.kext",
        "path": "Extensions/ApplePlatformEnabler.kext",
        "children": [
          {
            "value": 136,
            "name": "Contents",
            "path": "Extensions/ApplePlatformEnabler.kext/Contents"
          }
        ]
      },
      {
        "value": 240,
        "name": "AppleRAID.kext",
        "path": "Extensions/AppleRAID.kext",
        "children": [
          {
            "value": 240,
            "name": "Contents",
            "path": "Extensions/AppleRAID.kext/Contents"
          }
        ]
      },
      {
        "value": 372,
        "name": "AppleRAIDCard.kext",
        "path": "Extensions/AppleRAIDCard.kext",
        "children": [
          {
            "value": 372,
            "name": "Contents",
            "path": "Extensions/AppleRAIDCard.kext/Contents"
          }
        ]
      },
      {
        "value": 80,
        "name": "AppleRTC.kext",
        "path": "Extensions/AppleRTC.kext",
        "children": [
          {
            "value": 80,
            "name": "Contents",
            "path": "Extensions/AppleRTC.kext/Contents"
          }
        ]
      },
      {
        "value": 148,
        "name": "AppleSDXC.kext",
        "path": "Extensions/AppleSDXC.kext",
        "children": [
          {
            "value": 148,
            "name": "Contents",
            "path": "Extensions/AppleSDXC.kext/Contents"
          }
        ]
      },
      {
        "value": 76,
        "name": "AppleSEP.kext",
        "path": "Extensions/AppleSEP.kext",
        "children": [
          {
            "value": 76,
            "name": "Contents",
            "path": "Extensions/AppleSEP.kext/Contents"
          }
        ]
      },
      {
        "value": 88,
        "name": "AppleSmartBatteryManager.kext",
        "path": "Extensions/AppleSmartBatteryManager.kext",
        "children": [
          {
            "value": 88,
            "name": "Contents",
            "path": "Extensions/AppleSmartBatteryManager.kext/Contents"
          }
        ]
      },
      {
        "value": 60,
        "name": "AppleSMBIOS.kext",
        "path": "Extensions/AppleSMBIOS.kext",
        "children": [
          {
            "value": 60,
            "name": "Contents",
            "path": "Extensions/AppleSMBIOS.kext/Contents"
          }
        ]
      },
      {
        "value": 116,
        "name": "AppleSMBusController.kext",
        "path": "Extensions/AppleSMBusController.kext",
        "children": [
          {
            "value": 116,
            "name": "Contents",
            "path": "Extensions/AppleSMBusController.kext/Contents"
          }
        ]
      },
      {
        "value": 56,
        "name": "AppleSMBusPCI.kext",
        "path": "Extensions/AppleSMBusPCI.kext",
        "children": [
          {
            "value": 56,
            "name": "Contents",
            "path": "Extensions/AppleSMBusPCI.kext/Contents"
          }
        ]
      },
      {
        "value": 120,
        "name": "AppleSMC.kext",
        "path": "Extensions/AppleSMC.kext",
        "children": [
          {
            "value": 120,
            "name": "Contents",
            "path": "Extensions/AppleSMC.kext/Contents"
          }
        ]
      },
      {
        "value": 172,
        "name": "AppleSMCLMU.kext",
        "path": "Extensions/AppleSMCLMU.kext",
        "children": [
          {
            "value": 172,
            "name": "Contents",
            "path": "Extensions/AppleSMCLMU.kext/Contents"
          }
        ]
      },
      {
        "value": 88,
        "name": "AppleSRP.kext",
        "path": "Extensions/AppleSRP.kext",
        "children": [
          {
            "value": 88,
            "name": "Contents",
            "path": "Extensions/AppleSRP.kext/Contents"
          }
        ]
      },
      {
        "value": 1936,
        "name": "AppleStorageDrivers.kext",
        "path": "Extensions/AppleStorageDrivers.kext",
        "children": [
          {
            "value": 1936,
            "name": "Contents",
            "path": "Extensions/AppleStora
      // ... (99 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]Frameworks/DirectoryService.framework/Versions"
          }
        ]
      },
      {
        "value": 1352,
        "name": "DiscRecording.framework",
        "path": "Frameworks/DiscRecording.framework",
        "children": [
          {
            "value": 1344,
            "name": "Versions",
            "path": "Frameworks/DiscRecording.framework/Versions"
          }
        ]
      },
      {
        "value": 1384,
        "name": "DiscRecordingUI.framework",
        "path": "Frameworks/DiscRecordingUI.framework",
        "children": [
          {
            "value": 1376,
            "name": "Versions",
            "path": "Frameworks/DiscRecordingUI.framework/Versions"
          }
        ]
      },
      {
        "value": 76,
        "name": "DiskArbitration.framework",
        "path": "Frameworks/DiskArbitration.framework",
        "children": [
          {
            "value": 68,
            "name": "Versions",
            "path": "Frameworks/DiskArbitration.framework/Versions"
          }
        ]
      },
      {
        "value": 32,
        "name": "DrawSprocket.framework",
        "path": "Frameworks/DrawSprocket.framework",
        "children": [
          {
            "value": 24,
            "name": "Versions",
            "path": "Frameworks/DrawSprocket.framework/Versions"
          }
        ]
      },
      {
        "value": 20,
        "name": "DVComponentGlue.framework",
        "path": "Frameworks/DVComponentGlue.framework",
        "children": [
          {
            "value": 12,
            "name": "Versions",
            "path": "Frameworks/DVComponentGlue.framework/Versions"
          }
        ]
      },
      {
        "value": 1420,
        "name": "DVDPlayback.framework",
        "path": "Frameworks/DVDPlayback.framework",
        "children": [
          {
            "value": 1412,
            "name": "Versions",
            "path": "Frameworks/DVDPlayback.framework/Versions"
          }
        ]
      },
      {
        "value": 232,
        "name": "EventKit.framework",
        "path": "Frameworks/EventKit.framework",
        "children": [
          {
            "value": 224,
            "name": "Versions",
            "path": "Frameworks/EventKit.framework/Versions"
          }
        ]
      },
      {
        "value": 32,
        "name": "ExceptionHandling.framework",
        "path": "Frameworks/ExceptionHandling.framework",
        "children": [
          {
            "value": 24,
            "name": "Versions",
            "path": "Frameworks/ExceptionHandling.framework/Versions"
          }
        ]
      },
      {
        "value": 32,
        "name": "ForceFeedback.framework",
        "path": "Frameworks/ForceFeedback.framework",
        "children": [
          {
            "value": 24,
            "name": "Versions",
            "path": "Frameworks/ForceFeedback.framework/Versions"
          }
        ]
      },
      {
        "value": 4228,
        "name": "Foundation.framework",
        "path": "Frameworks/Foundation.framework",
        "children": [
          {
            "value": 4216,
            "name": "Versions",
            "path": "Frameworks/Foundation.framework/Versions"
          }
        ]
      },
      {
        "value": 52,
        "name": "FWAUserLib.framework",
        "path": "Frameworks/FWAUserLib.framework",
        "children": [
          {
            "value": 44,
            "name": "Versions",
            "path": "Frameworks/FWAUserLib.framework/Versions"
          }
        ]
      },
      {
        "value": 60,
        "name": "GameController.framework",
        "path": "Frameworks/GameController.framework",
        "children": [
          {
            "value": 52,
            "name": "Versions",
            "path": "Frameworks/GameController.framework/Versions"
          }
        ]
      },
      {
        "value": 44244,
        "name": "GameKit.framework",
        "path": "Frameworks/GameKit.framework",
        "children": [
          {
            "value": 44236,
            "name": "Versions",
            "path": "Frameworks/GameKit.framework/Versions"
          }
        ]
      },
      {
        "value": 132,
        "name": "GLKit.framework",
        "path": "Frameworks/GLKit.framework",
        "children": [
          {
            "value": 124,
            "name": "Versions",
            "path": "Frameworks/GLKit.framework/Versions"
          }
        ]
      },
      {
        "value": 1740,
        "name": "GLUT.framework",
        "path": "Frameworks/GLUT.framework",
        "children": [
          {
            "value": 1732,
            "name": "Versions",
            "path": "Frameworks/GLUT.framework/Versions"
          }
        ]
      },
      {
        "value": 280,
        "name": "GSS.framework",
        "path": "Frameworks/GSS.framework",
        "children": [
          {
            "value": 272,
            "name": "Versions",
            "path": "Frameworks/GSS.framework/Versions"
          }
        ]
      },
      {
        "value": 236,
        "name": "ICADevices.framework",
        "path": "Frameworks/ICADevices.framework",
        "children": [
          {
            "value": 228,
            "name": "Versions",
         
      // ... (228 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]name": "Localization.prefPane",
        "path": "PreferencePanes/Localization.prefPane",
        "children": [
          {
            "value": 3468,
            "name": "Contents",
            "path": "PreferencePanes/Localization.prefPane/Contents"
          }
        ]
      },
      {
        "value": 23180,
        "name": "Mouse.prefPane",
        "path": "PreferencePanes/Mouse.prefPane",
        "children": [
          {
            "value": 23180,
            "name": "Contents",
            "path": "PreferencePanes/Mouse.prefPane/Contents"
          }
        ]
      },
      {
        "value": 20588,
        "name": "Network.prefPane",
        "path": "PreferencePanes/Network.prefPane",
        "children": [
          {
            "value": 20588,
            "name": "Contents",
            "path": "PreferencePanes/Network.prefPane/Contents"
          }
        ]
      },
      {
        "value": 1512,
        "name": "Notifications.prefPane",
        "path": "PreferencePanes/Notifications.prefPane",
        "children": [
          {
            "value": 1512,
            "name": "Contents",
            "path": "PreferencePanes/Notifications.prefPane/Contents"
          }
        ]
      },
      {
        "value": 7648,
        "name": "ParentalControls.prefPane",
        "path": "PreferencePanes/ParentalControls.prefPane",
        "children": [
          {
            "value": 7648,
            "name": "Contents",
            "path": "PreferencePanes/ParentalControls.prefPane/Contents"
          }
        ]
      },
      {
        "value": 4060,
        "name": "PrintAndScan.prefPane",
        "path": "PreferencePanes/PrintAndScan.prefPane",
        "children": [
          {
            "value": 4060,
            "name": "Contents",
            "path": "PreferencePanes/PrintAndScan.prefPane/Contents"
          }
        ]
      },
      {
        "value": 1904,
        "name": "Profiles.prefPane",
        "path": "PreferencePanes/Profiles.prefPane",
        "children": [
          {
            "value": 1904,
            "name": "Contents",
            "path": "PreferencePanes/Profiles.prefPane/Contents"
          }
        ]
      },
      {
        "value": 6280,
        "name": "Security.prefPane",
        "path": "PreferencePanes/Security.prefPane",
        "children": [
          {
            "value": 6280,
            "name": "Contents",
            "path": "PreferencePanes/Security.prefPane/Contents"
          }
        ]
      },
      {
        "value": 9608,
        "name": "SharingPref.prefPane",
        "path": "PreferencePanes/SharingPref.prefPane",
        "children": [
          {
            "value": 9608,
            "name": "Contents",
            "path": "PreferencePanes/SharingPref.prefPane/Contents"
          }
        ]
      },
      {
        "value": 2204,
        "name": "Sound.prefPane",
        "path": "PreferencePanes/Sound.prefPane",
        "children": [
          {
            "value": 2204,
            "name": "Contents",
            "path": "PreferencePanes/Sound.prefPane/Contents"
          }
        ]
      },
      {
        "value": 1072,
        "name": "Speech.prefPane",
        "path": "PreferencePanes/Speech.prefPane",
        "children": [
          {
            "value": 1072,
            "name": "Contents",
            "path": "PreferencePanes/Speech.prefPane/Contents"
          }
        ]
      },
      {
        "value": 1112,
        "name": "Spotlight.prefPane",
        "path": "PreferencePanes/Spotlight.prefPane",
        "children": [
          {
            "value": 1112,
            "name": "Contents",
            "path": "PreferencePanes/Spotlight.prefPane/Contents"
          }
        ]
      },
      {
        "value": 2040,
        "name": "StartupDisk.prefPane",
        "path": "PreferencePanes/StartupDisk.prefPane",
        "children": [
          {
            "value": 2040,
            "name": "Contents",
            "path": "PreferencePanes/StartupDisk.prefPane/Contents"
          }
        ]
      },
      {
        "value": 3080,
        "name": "TimeMachine.prefPane",
        "path": "PreferencePanes/TimeMachine.prefPane",
        "children": [
          {
            "value": 3080,
            "name": "Contents",
            "path": "PreferencePanes/TimeMachine.prefPane/Contents"
          }
        ]
      },
      {
        "value": 93312,
        "name": "Trackpad.prefPane",
        "path": "PreferencePanes/Trackpad.prefPane",
        "children": [
          {
            "value": 93312,
            "name": "Contents",
            "path": "PreferencePanes/Trackpad.prefPane/Contents"
          }
        ]
      },
      {
        "value": 7680,
        "name": "UniversalAccessPref.prefPane",
        "path": "PreferencePanes/UniversalAccessPref.prefPane",
        "children": [
          {
            "value": 7680,
            "name": "Contents",
            "path": "PreferencePanes/UniversalAccessPref.prefPane/Contents"
          }
        ]
      },
      {
        "value": 640,
        "name": "Xsan.prefPane",
        "path": "PreferencePanes/Xsan.prefPane",
        "children": [
          {
            "value": 640,
            "name": "Contents",
            "path": "PreferencePanes/Xsan.prefPane/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 224,
    "name": "Printers",
    "path": "Printers",
    "children": [
      {
        "value": 224,
        "name": "Libraries",
        "path": "Printers/Libraries",
        "children": [
          {
            "value": 24,
            "name": "USBGenericPrintingClass.plugin",
            "path": "Printers/Libraries/USBGenericPrintingClass.plugin"
          },
          {
            "value": 24,
            "name": "USBGenericTOPrintingClass.plugin",
            "path": "Printers/Libraries/USBGenericTOPrintingClass.plugin"
          }
        ]
      }
    ]
  },
  {
    "value": 586092,
    "name": "PrivateFrameworks",
    "path": "PrivateFrameworks",
    "children": [
      {
        "value": 52,
        "name": "AccessibilityBundles.framework",
        "path": "PrivateFrameworks/AccessibilityBundles.framework",
        "children": [
          {
            "value": 44,
            "name": "Versions",
            "path": "PrivateFrameworks/AccessibilityBundles.framework/Versions"
          }
        ]
      },
      {
        "value": 348,
        "name": "AccountsDaemon.framework",
        "path": "PrivateFrameworks/AccountsDaemon.framework",
        "children": [
          {
            "value": 332,
            "name": "Versions",
            "path": "PrivateFrameworks/AccountsDaemon.framework/Versions"
          },
          {
            "value": 8,
            "name": "XPCServices",
            "path": "PrivateFrameworks/AccountsDaemon.framework/XPCServices"
          }
        ]
      },
      {
        "value": 168,
        "name": "Admin.framework",
        "path": "PrivateFrameworks/Admin.framework",
        "children": [
          {
            "value": 160,
            "name": "Versions",
            "path": "PrivateFrameworks/Admin.framework/Versions"
          }
        ]
      },
      {
        "value": 408,
        "name": "AirPortDevices.framework",
        "path": "PrivateFrameworks/AirPortDevices.framework",
        "children": [
          {
            "value": 408,
            "name": "Versions",
            "path": "PrivateFrameworks/AirPortDevices.framework/Versions"
          }
        ]
      },
      {
        "value": 1324,
        "name": "AirTrafficHost.framework",
        "path": "PrivateFrameworks/AirTrafficHost.framework",
        "children": [
          {
            "value": 1276,
            "name": "Versions",
            "path": "PrivateFrameworks/AirTrafficHost.framework/Versions"
          }
        ]
      },
      {
        "value": 2408,
        "name": "Altitude.framework",
        "path": "PrivateFrameworks/Altitude.framework",
        "children": [
          {
            "value": 2400,
            "name": "Versions",
            "path": "PrivateFrameworks/Altitude.framework/Versions"
          }
        ]
      },
      {
        "value": 224,
        "name": "AOSAccounts.framework",
        "path": "PrivateFrameworks/AOSAccounts.framework",
        "children": [
          {
            "value": 216,
            "name": "Versions",
            "path": "PrivateFrameworks/AOSAccounts.framework/Versions"
          }
        ]
      },
      {
        "value": 4672,
        "name": "AOSKit.framework",
        "path": "PrivateFrameworks/AOSKit.framework",
        "children": [
          {
            "value": 4656,
            "name": "Versions",
            "path": "PrivateFrameworks/AOSKit.framework/Versions"
          }
        ]
      },
      // ... (288 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
  },
  {
    "value": 2988,
    "name": "QuickLook",
    "path": "QuickLook",
    "children": [
      {
        "value": 8,
        "name": "Audio.qlgenerator",
        "path": "QuickLook/Audio.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/Audio.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Bookmark.qlgenerator",
        "path": "QuickLook/Bookmark.qlgenerator",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "QuickLook/Bookmark.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Clippings.qlgenerator",
        "path": "QuickLook/Clippings.qlgenerator",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "QuickLook/Clippings.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 232,
        "name": "Contact.qlgenerator",
        "path": "QuickLook/Contact.qlgenerator",
        "children": [
          {
            "value": 232,
            "name": "Contents",
            "path": "QuickLook/Contact.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "EPS.qlgenerator",
        "path": "QuickLook/EPS.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/EPS.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Font.qlgenerator",
        "path": "QuickLook/Font.qlgenerator",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "QuickLook/Font.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 1432,
        "name": "iCal.qlgenerator",
        "path": "QuickLook/iCal.qlgenerator",
        "children": [
          {
            "value": 1432,
            "name": "Contents",
            "path": "QuickLook/iCal.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "iChat.qlgenerator",
        "path": "QuickLook/iChat.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/iChat.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "Icon.qlgenerator",
        "path": "QuickLook/Icon.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/Icon.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "Image.qlgenerator",
        "path": "QuickLook/Image.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/Image.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "LocPDF.qlgenerator",
        "path": "QuickLook/LocPDF.qlgenerator",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "QuickLook/LocPDF.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "Mail.qlgenerator",
        "path": "QuickLook/Mail.qlgenerator",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "QuickLook/Mail.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Movie.qlgenerator",
        "path": "QuickLook/Movie.qlgenerator",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "QuickLook/Movie.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "Notes.qlgenerator",
        "path": "QuickLook/Notes.qlgenerator",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "QuickLook/Notes.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 24,
        "name": "Office.qlgenerator",
        "path": "QuickLook/Office.qlgenerator",
        "children": [
          {
            "value": 24,
            "name": "Contents",
            "path": "QuickLook/Office.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "Package.qlgenerator",
        "path": "QuickLook/Package.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/Package.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "PDF.qlgenerator",
        "path": "QuickLook/PDF.qlgenerator",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "QuickLook/PDF.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SceneKit.qlgenerator",
        "path": "QuickLook/SceneKit.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/SceneKit.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 36,
        "name": "Security.qlgenerator",
        "path": "QuickLook/Security.qlgenerator",
        "children": [
          {
            "value": 36,
            "name": "Contents",
            "path": "QuickLook/Security.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 1060,
        "name": "StandardBundles.qlgenerator",
        "path": "QuickLook/StandardBundles.qlgenerator",
        "children": [
          {
            "value": 1060,
            "name": "Contents",
            "path": "QuickLook/StandardBundles.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Text.qlgenerator",
        "path": "QuickLook/Text.qlgenerator",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "QuickLook/Text.qlgenerator/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "Web.qlgenerator",
        "path": "QuickLook/Web.qlgenerator",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "QuickLook/Web.qlgenerator/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 17888,
    "name": "QuickTime",
    "path": "QuickTime",
    "children": [
      {
        "value": 24,
        "name": "AppleGVAHW.component",
        "path": "QuickTime/AppleGVAHW.component",
        "children": [
          {
            "value": 24,
            "name": "Contents",
            "path": "QuickTime/AppleGVAHW.component/Contents"
          }
        ]
      },
      {
        "value": 60,
        "name": "ApplePixletVideo.component",
        "path": "QuickTime/ApplePixletVideo.component",
        "children": [
          {
            "value": 60,
            "name": "Contents",
            "path": "QuickTime/ApplePixletVideo.component/Contents"
          }
        ]
      },
      {
        "value": 216,
        "name": "AppleProResDecoder.component",
        "path": "QuickTime/AppleProResDecoder.component",
        "children": [
          {
            "value": 216,
            "name": "Contents",
            "path": "QuickTime/AppleProResDecoder.component/Contents"
          }
        ]
      },
      {
        "value": 756,
        "name": "AppleVAH264HW.component",
        "path": "QuickTime/AppleVAH264HW.component",
        "children": [
          {
            "value": 756,
            "name": "Contents",
            "path": "QuickTime/AppleVAH264HW.component/Contents"
          }
        ]
      },
      {
        "value": 24,
        "name": "QuartzComposer.component",
        "path": "QuickTime/QuartzComposer.component",
        "children": [
          {
            "value": 24,
            "name": "Contents",
            "path": "QuickTime/QuartzComposer.component/Contents"
          }
        ]
      },
      {
        "value": 520,
        "name": "QuickTime3GPP.component",
        "path": "QuickTime/QuickTime3GPP.component",
        "children": [
          {
            "value": 520,
            "name": "Contents",
            "path": "QuickTime/QuickTime3GPP.component/Contents"
          }
        ]
      },
      {
        "value": 11548,
        "name": "QuickTimeComponents.component",
        "path": "QuickTime/QuickTimeComponents.component",
        "children": [
          {
            "value": 11548,
            "name": "Contents",
            "path": "QuickTime/QuickTimeComponents.component/Contents"
          }
        ]
      },
      {
        "value": 76,
        "name": "QuickTimeFireWireDV.component",
        "path": "QuickTime/QuickTimeFireWireDV.component",
        "children": [
          {
            "value": 76,
            "name": "Contents",
            "path": "QuickTime/QuickTimeFireWireDV.component/Contents"
          }
        ]
      },
      {
        "value": 1592,
        "name": "QuickTimeH264.component",
        "path": "QuickTime/QuickTimeH264.component",
        "children": [
          {
            "value": 1592,
            "name": "Contents",
            "path": "QuickTime/QuickTimeH264.component/Contents"
          }
        ]
      },
      {
        "value": 64,
        "name": "QuickTimeIIDCDigitizer.component",
        "path": "QuickTime/QuickTimeIIDCDigitizer.component",
        "children": [
          {
            "value": 64,
            "name": "Contents",
            "path": "QuickTime/QuickTimeIIDCDigitizer.component/Contents"
          }
        ]
      },
      {
        "value": 832,
        "name": "QuickTimeImporters.component",
        "path": "QuickTime/QuickTimeImporters.component",
        "children": [
          {
            "value": 832,
            "name": "Contents",
            "path": "QuickTime/QuickTimeImporters.component/Contents"
          }
        ]
      },
      {
        "value": 200,
        "name": "QuickTimeMPEG.component",
        "path": "QuickTime/QuickTimeMPEG.component",
        "children": [
          {
            "value": 200,
            "name": "Contents",
            "path": "QuickTime/QuickTimeMPEG.component/Contents"
          }
        ]
      },
      {
        "value": 564,
        "name": "QuickTimeMPEG4.component",
        "path": "QuickTime/QuickTimeMPEG4.component",
        "children": [
          {
            "value": 564,
            "name": "Contents",
            "path": "QuickTime/QuickTimeMPEG4.component/Contents"
          }
        ]
      },
      {
        "value": 968,
        "name": "QuickTimeStreaming.component",
        "path": "QuickTime/QuickTimeStreaming.component",
        "children": [
          {
            "value": 968,
            "name": "Contents",
            "path": "QuickTime/QuickTimeStreaming.component/Contents"
          }
        ]
      },
      {
        "value": 120,
        "name": "QuickTimeUSBVDCDigitizer.component",
        "path": "QuickTime/QuickTimeUSBVDCDigitizer.component",
        "children": [
          {
            "value": 120,
            "name": "Contents",
            "path": "QuickTime/QuickTimeUSBVDCDigitizer.component/Contents"
          }
        ]
      },
      {
        "value": 324,
        "name": "QuickTimeVR.component",
        "path": "QuickTime/QuickTimeVR.component",
        "children": [
          {
            "value": 324,
            "name": "Contents",
            "path": "QuickTime/QuickTimeVR.component/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 28,
    "name": "QuickTimeJava",
    "path": "QuickTimeJava",
    "children": [
      {
        "value": 28,
        "name": "QuickTimeJava.bundle",
        "path": "QuickTimeJava/QuickTimeJava.bundle",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "QuickTimeJava/QuickTimeJava.bundle/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 20,
    "name": "Recents",
    "path": "Recents",
    "children": [
      {
        "value": 20,
        "name": "Plugins",
        "path": "Recents/Plugins",
        "children": [
          {
            "value": 36,
            "name": "AddressBook.assistantBundle",
            "path": "Assistant/Plugins/AddressBook.assistantBundle"
          },
          {
            "value": 8,
            "name": "GenericAddressHandler.addresshandler",
            "path": "Recents/Plugins/GenericAddressHandler.addresshandler"
          },
          {
            "value": 12,
            "name": "MapsRecents.addresshandler",
            "path": "Recents/Plugins/MapsRecents.addresshandler"
          }
        ]
      }
    ]
  },
  {
    "value": 12,
    "name": "Sandbox",
    "path": "Sandbox",
    "children": [
      {
        "value": 12,
        "name": "Profiles",
        "path": "Sandbox/Profiles"
      }
    ]
  },
  {
    "value": 1052,
    "name": "ScreenSavers",
    "path": "ScreenSavers",
    "children": [
      {
        "value": 8,
        "name": "FloatingMessage.saver",
        "path": "ScreenSavers/FloatingMessage.saver",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "ScreenSavers/FloatingMessage.saver/Contents"
          }
        ]
      },
      {
        "value": 360,
        "name": "Flurry.saver",
        "path": "ScreenSavers/Flurry.saver",
        "children": [
          {
            "value": 360,
            "name": "Contents",
            "path": "ScreenSavers/Flurry.saver/Contents"
          }
        ]
      },
      {
        "value": 568,
        "name": "iTunes Artwork.saver",
        "path": "ScreenSavers/iTunes Artwork.saver",
        "children": [
          {
            "value": 568,
            "name": "Contents",
            "path": "ScreenSavers/iTunes Artwork.saver/Contents"
          }
        ]
      },
      {
        "value": 52,
        "name": "Random.saver",
        "path": "ScreenSavers/Random.saver",
        "children": [
          {
            "value": 52,
            "name": "Contents",
            "path": "ScreenSavers/Random.saver/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 1848,
    "name": "ScreenReader",
    "path": "ScreenReader",
    "children": [
      {
        "value": 556,
        "name": "BrailleDrivers",
        "path": "ScreenReader/BrailleDrivers",
        "children": [
          {
            "value": 28,
            "name": "Alva6 Series.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Alva6 Series.brailledriver"
          },
          {
            "value": 16,
            "name": "Alva.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Alva.brailledriver"
          },
          {
            "value": 28,
            "name": "BrailleConnect.brailledriver",
            "path": "ScreenReader/BrailleDrivers/BrailleConnect.brailledriver"
          },
          {
            "value": 24,
            "name": "BrailleNoteApex.brailledriver",
            "path": "ScreenReader/BrailleDrivers/BrailleNoteApex.brailledriver"
          },
          {
            "value": 16,
            "name": "BrailleNote.brailledriver",
            "path": "ScreenReader/BrailleDrivers/BrailleNote.brailledriver"
          },
          {
            "value": 24,
            "name": "BrailleSense.brailledriver",
            "path": "ScreenReader/BrailleDrivers/BrailleSense.brailledriver"
          },
          {
            "value": 28,
            "name": "Brailliant2.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Brailliant2.brailledriver"
          },
          {
            "value": 28,
            "name": "Brailliant.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Brailliant.brailledriver"
          },
          {
            "value": 16,
            "name": "Deininger.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Deininger.brailledriver"
          },
          {
            "value": 20,
            "name": "EasyLink.brailledriver",
            "path": "ScreenReader/BrailleDrivers/EasyLink.brailledriver"
          },
          {
            "value": 28,
            "name": "Eurobraille.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Eurobraille.brailledriver"
          },
          {
            "value": 28,
            "name": "FreedomScientific.brailledriver",
            "path": "ScreenReader/BrailleDrivers/FreedomScientific.brailledriver"
          },
          {
            "value": 32,
            "name": "HandyTech.brailledriver",
            "path": "ScreenReader/BrailleDrivers/HandyTech.brailledriver"
          },
          {
            "value": 20,
            "name": "HIMSDriver.brailledriver",
            "path": "ScreenReader/BrailleDrivers/HIMSDriver.brailledriver"
          },
          {
            "value": 28,
            "name": "KGSDriver.brailledriver",
            "path": "ScreenReader/BrailleDrivers/KGSDriver.brailledriver"
          },
          {
            "value": 28,
            "name": "MDV.brailledriver",
            "path": "ScreenReader/BrailleDrivers/MDV.brailledriver"
          },
          {
            "value": 24,
            "name": "NinepointSystems.brailledriver",
            "path": "ScreenReader/BrailleDrivers/NinepointSystems.brailledriver"
          },
          {
            "value": 24,
            "name": "Papenmeier.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Papenmeier.brailledriver"
          },
          {
            "value": 28,
            "name": "Refreshabraille.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Refreshabraille.brailledriver"
          },
          {
            "value": 32,
            "name": "Seika.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Seika.brailledriver"
          },
          {
            "value": 16,
            "name": "SyncBraille.brailledriver",
            "path": "ScreenReader/BrailleDrivers/SyncBraille.brailledriver"
          },
          {
            "value": 24,
            "name": "VarioPro.brailledriver",
            "path": "ScreenReader/BrailleDrivers/VarioPro.brailledriver"
          },
          {
            "value": 16,
            "name": "Voyager.brailledriver",
            "path": "ScreenReader/BrailleDrivers/Voyager.brailledriver"
          }
        ]
      },
      {
        "value": 1292,
        "name": "BrailleTables",
        "path": "ScreenReader/BrailleTables",
        "children": [
          {
            "value": 1292,
            "name": "Duxbury.brailletable",
            "path": "ScreenReader/BrailleTables/Duxbury.brailletable"
          }
        ]
      }
    ]
  },
  {
    "value": 1408,
    "name": "ScriptingAdditions",
    "path": "ScriptingAdditions",
    "children": [
      {
        "value": 8,
        "name": "DigitalHub Scripting.osax",
        "path": "ScriptingAdditions/DigitalHub Scripting.osax",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "ScriptingAdditions/DigitalHub Scripting.osax/Contents"
          }
        ]
      },
      {
        "value": 1400,
        "name": "StandardAdditions.osax",
        "path": "ScriptingAdditions/StandardAdditions.osax",
        "children": [
          {
            "value": 1400,
            "name": "Contents",
            "path": "ScriptingAdditions/StandardAdditions.osax/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 0,
    "name": "ScriptingDefinitions",
    "path": "ScriptingDefinitions"
  },
  {
    "value": 0,
    "name": "SDKSettingsPlist",
    "path": "SDKSettingsPlist"
  },
  {
    "value": 312,
    "name": "Security",
    "path": "Security",
    "children": [
      {
        "value": 100,
        "name": "dotmac_tp.bundle",
        "path": "Security/dotmac_tp.bundle",
        "children": [
          {
            "value": 100,
            "name": "Contents",
            "path": "Security/dotmac_tp.bundle/Contents"
          }
        ]
      },
      {
        "value": 72,
        "name": "ldapdl.bundle",
        "path": "Security/ldapdl.bundle",
        "children": [
          {
            "value": 72,
            "name": "Contents",
            "path": "Security/ldapdl.bundle/Contents"
          }
        ]
      },
      {
        "value": 132,
        "name": "tokend",
        "path": "Security/tokend",
        "children": [
          {
            "value": 132,
            "name": "uiplugins",
            "path": "Security/tokend/uiplugins"
          }
        ]
      }
    ]
  },
  {
    "value": 18208,
    "name": "Services",
    "path": "Services",
    "children": [
      {
        "value": 0,
        "name": "Addto iTunes as a Spoken Track.workflow",
        "path": "Services/Addto iTunes as a Spoken Track.workflow",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "Services/Addto iTunes as a Spoken Track.workflow/Contents"
          }
        ]
      },
      {
        "value": 14308,
        "name": "AppleSpell.service",
        "path": "Services/AppleSpell.service",
        "children": [
          {
            "value": 14308,
            "name": "Contents",
            "path": "Services/AppleSpell.service/Contents"
          }
        ]
      },
      {
        "value": 556,
        "name": "ChineseTextConverterService.app",
        "path": "Services/ChineseTextConverterService.app",
        "children": [
          {
            "value": 556,
            "name": "Contents",
            "path": "Services/ChineseTextConverterService.app/Contents"
          }
        ]
      },
      {
        "value": 48,
        "name": "EncodeSelected Audio Files.workflow",
        "path": "Services/EncodeSelected Audio Files.workflow",
        "children": [
          {
            "value": 48,
            "name": "Contents",
            "path": "Services/EncodeSelected Audio Files.workflow/Contents"
          }
        ]
      },
      {
        "value": 40,
        "name": "EncodeSelected Video Files.workflow",
        "path": "Services/EncodeSelected Video Files.workflow",
        "children": [
          {
            "value": 40,
            "name": "Contents",
            "path": "Services/EncodeSelected Video Files.workflow/Contents"
          }
        ]
      },
      {
        "value": 1344,
        "name": "ImageCaptureService.app",
        "path": "Services/ImageCaptureService.app",
        "children": [
          {
            "value": 1344,
            "name": "Contents",
            "path": "Services/ImageCaptureService.app/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "OpenSpell.service",
        "path": "Services/OpenSpell.service",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "Services/OpenSpell.service/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "SetDesktop Picture.workflow",
        "path": "Services/SetDesktop Picture.workflow",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "Services/SetDesktop Picture.workflow/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "ShowAddress in Google Maps.workflow",
        "path": "Services/ShowAddress in Google Maps.workflow",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "Services/ShowAddress in Google Maps.workflow/Contents"
          }
        ]
      },
      {
        "value": 60,
        "name": "ShowMap.workflow",
        "path": "Services/ShowMap.workflow",
        "children": [
          {
            "value": 60,
            "name": "Contents",
            "path": "Services/ShowMap.workflow/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SpeechService.service",
        "path": "Services/SpeechService.service",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Services/SpeechService.service/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "Spotlight.service",
        "path": "Services/Spotlight.service",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "Services/Spotlight.service/Contents"
          }
        ]
      },
      {
        "value": 1816,
        "name": "SummaryService.app",
        "path": "Services/SummaryService.app",
        "children": [
          {
            "value": 1816,
            "name": "Contents",
            "path": "Services/SummaryService.app/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 700,
    "name": "Sounds",
    "path": "Sounds"
  },
  {
    "value": 1512668,
    "name": "Speech",
    "path": "Speech",
    "children": [
      {
        "value": 2804,
        "name": "Recognizers",
        "path": "Speech/Recognizers",
        "children": [
          {
            "value": 2804,
            "name": "AppleSpeakableItems.SpeechRecognizer",
            "path": "Speech/Recognizers/AppleSpeakableItems.SpeechRecognizer"
          }
        ]
      },
      {
        "value": 6684,
        "name": "Synthesizers",
        "path": "Speech/Synthesizers",
        "children": [
          {
            "value": 800,
            "name": "MacinTalk.SpeechSynthesizer",
            "path": "Speech/Synthesizers/MacinTalk.SpeechSynthesizer"
          },
          {
            "value": 3468,
            "name": "MultiLingual.SpeechSynthesizer",
            "path": "Speech/Synthesizers/MultiLingual.SpeechSynthesizer"
          },
          {
            "value": 2416,
            "name": "Polyglot.SpeechSynthesizer",
            "path": "Speech/Synthesizers/Polyglot.SpeechSynthesizer"
          }
        ]
      },
      {
        "value": 1503180,
        "name": "Voices",
        "path": "Speech/Voices",
        "children": [
          {
            "value": 1540,
            "name": "Agnes.SpeechVoice",
            "path": "Speech/Voices/Agnes.SpeechVoice"
          },
          {
            "value": 20,
            "name": "Albert.SpeechVoice",
            "path": "Speech/Voices/Albert.SpeechVoice"
          },
          {
            "value": 412132,
            "name": "Alex.SpeechVoice",
            "path": "Speech/Voices/Alex.SpeechVoice"
          },
          {
            "value": 624,
            "name": "AliceCompact.SpeechVoice",
            "path": "Speech/Voices/AliceCompact.SpeechVoice"
          },
          {
            "value": 908,
            "name": "AlvaCompact.SpeechVoice",
            "path": "Speech/Voices/AlvaCompact.SpeechVoice"
          },
          {
            "value": 668,
            "name": "AmelieCompact.SpeechVoice",
            "path": "Speech/Voices/AmelieCompact.SpeechVoice"
          },
          {
            "value": 1016,
            "name": "AnnaCompact.SpeechVoice",
            "path": "Speech/Voices/AnnaCompact.SpeechVoice"
          },
          {
            "value": 12,
            "name": "BadNews.SpeechVoice",
            "path": "Speech/Voices/BadNews.SpeechVoice"
          },
          {
            "value": 20,
            "name": "Bahh.SpeechVoice",
            "path": "Speech/Voices/Bahh.SpeechVoice"
          },
          {
            "value": 48,
            "name": "Bells.SpeechVoice",
            "path": "Speech/Voices/Bells.SpeechVoice"
          },
          {
            "value": 20,
            "name": "Boing.SpeechVoice",
            "path": "Speech/Voices/Boing.SpeechVoice"
          },
          {
            "value": 1684,
            "name": "Bruce.SpeechVoice",
            "path": "Speech/Voices/Bruce.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Bubbles.SpeechVoice",
            "path": "Speech/Voices/Bubbles.SpeechVoice"
          },
          {
            "value": 24,
            "name": "Cellos.SpeechVoice",
            "path": "Speech/Voices/Cellos.SpeechVoice"
          },
          {
            "value": 720,
            "name": "DamayantiCompact.SpeechVoice",
            "path": "Speech/Voices/DamayantiCompact.SpeechVoice"
          },
          {
            "value": 1000,
            "name": "DanielCompact.SpeechVoice",
            "path": "Speech/Voices/DanielCompact.SpeechVoice"
          },
          {
            "value": 24,
            "name": "Deranged.SpeechVoice",
            "path": "Speech/Voices/Deranged.SpeechVoice"
          },
          {
            "value": 740,
            "name": "EllenCompact.SpeechVoice",
            "path": "Speech/Voices/EllenCompact.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Fred.SpeechVoice",
            "path": "Speech/Voices/Fred.SpeechVoice"
          },
          {
            "value": 12,
            "name": "GoodNews.SpeechVoice",
            "path": "Speech/Voices/GoodNews.SpeechVoice"
          },
          {
            "value": 28,
            "name": "Hysterical.SpeechVoice",
            "path": "Speech/Voices/Hysterical.SpeechVoice"
          },
          {
            "value": 492,
            "name": "IoanaCompact.SpeechVoice",
            "path": "Speech/Voices/IoanaCompact.SpeechVoice"
          },
          {
            "value": 596,
            "name": "JoanaCompact.SpeechVoice",
            "path": "Speech/Voices/JoanaCompact.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Junior.SpeechVoice",
            "path": "Speech/Voices/Junior.SpeechVoice"
          },
          {
            "value": 1336,
            "name": "KanyaCompact.SpeechVoice",
            "path": "Speech/Voices/KanyaCompact.SpeechVoice"
          },
          {
            "value": 1004,
            "name": "KarenCompact.SpeechVoice",
            "path": "Speech/Voices/KarenCompact.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Kathy.SpeechVoice",
            "path": "Speech/Voices/Kathy.SpeechVoice"
          },
          {
            "value": 408836,
            "name": "Kyoko.SpeechVoice",
            "path": "Speech/Voices/Kyoko.SpeechVoice"
          },
          {
            "value": 2620,
            "name": "KyokoCompact.SpeechVoice",
            "path": "Speech/Voices/KyokoCompact.SpeechVoice"
          },
          {
            "value": 496,
            "name": "LauraCompact.SpeechVoice",
            "path": "Speech/Voices/LauraCompact.SpeechVoice"
          },
          {
            "value": 2104,
            "name": "LekhaCompact.SpeechVoice",
            "path": "Speech/Voices/LekhaCompact.SpeechVoice"
          },
          {
            "value": 548,
            "name": "LucianaCompact.SpeechVoice",
            "path": "Speech/Voices/LucianaCompact.SpeechVoice"
          },
          {
            "value": 504,
            "name": "MariskaCompact.SpeechVoice",
            "path": "Speech/Voices/MariskaCompact.SpeechVoice"
          },
          {
            "value": 2092,
            "name": "Mei-JiaCompact.SpeechVoice",
            "path": "Speech/Voices/Mei-JiaCompact.SpeechVoice"
          },
          {
            "value": 1020,
            "name": "MelinaCompact.SpeechVoice",
            "path": "Speech/Voices/MelinaCompact.SpeechVoice"
          },
          {
            "value": 2160,
            "name": "MilenaCompact.SpeechVoice",
            "path": "Speech/Voices/MilenaCompact.SpeechVoice"
          },
          {
            "value": 728,
            "name": "MoiraCompact.SpeechVoice",
            "path": "Speech/Voices/MoiraCompact.SpeechVoice"
          },
          {
            "value": 612,
            "name": "MonicaCompact.SpeechVoice",
            "path": "Speech/Voices/MonicaCompact.SpeechVoice"
          },
          {
            "value": 824,
            "name": "NoraCompact.SpeechVoice",
            "path": "Speech/Voices/NoraCompact.SpeechVoice"
          },
          {
            "value": 24,
            "name": "Organ.SpeechVoice",
            "path": "Speech/Voices/Organ.SpeechVoice"
          },
          {
            "value": 664,
            "name": "PaulinaCompact.SpeechVoice",
            "path": "Speech/Voices/PaulinaCompact.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Princess.SpeechVoice",
            "path": "Speech/Voices/Princess.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Ralph.SpeechVoice",
            "path": "Speech/Voices/Ralph.SpeechVoice"
          },
          {
            "value": 908,
            "name": "SamanthaCompact.SpeechVoice",
            "path": "Speech/Voices/SamanthaCompact.SpeechVoice"
          },
          {
            "value": 828,
            "name": "SaraCompact.SpeechVoice",
            "path": "Speech/Voices/SaraCompact.SpeechVoice"
          },
          {
            "value": 664,
            "name": "SatuCompact.SpeechVoice",
            "path": "Speech/Voices/SatuCompact.SpeechVoice"
          },
          {
            "value": 2336,
            "name": "Sin-jiCompact.SpeechVoice",
            "path": "Speech/Voices/Sin-jiCompact.SpeechVoice"
          },
          {
            "value": 2856,
            "name": "TarikCompact.SpeechVoice",
            "path": "Speech/Voices/TarikCompact.SpeechVoice"
          },
          {
            "value": 948,
            "name": "TessaCompact.SpeechVoice",
            "path": "Speech/Voices/TessaCompact.SpeechVoice"
          },
          {
            "value": 660,
            "name": "ThomasCompact.SpeechVoice",
            "path": "Speech/Voices/ThomasCompact.SpeechVoice"
          },
          {
            "value": 610156,
            "name": "Ting-Ting.SpeechVoice",
            "path": "Speech/Voices/Ting-Ting.SpeechVoice"
          },
          {
            "value": 1708,
            "name": "Ting-TingCompact.SpeechVoice",
            "path": "Speech/Voices/Ting-TingCompact.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Trinoids.SpeechVoice",
            "path": "Speech/Voices/Trinoids.SpeechVoice"
          },
          {
            "value": 28632,
            "name": "Vicki.SpeechVoice",
            "path": "Speech/Voices/Vicki.SpeechVoice"
          },
          {
            "value": 1664,
            "name": "Victoria.SpeechVoice",
            "path": "Speech/Voices/Victoria.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Whisper.SpeechVoice",
            "path": "Speech/Voices/Whisper.SpeechVoice"
          },
          {
            "value": 992,
            "name": "XanderCompact.SpeechVoice",
            "path": "Speech/Voices/XanderCompact.SpeechVoice"
          },
          {
            "value": 756,
            "name": "YeldaCompact.SpeechVoice",
            "path": "Speech/Voices/YeldaCompact.SpeechVoice"
          },
          {
            "value": 728,
            "name": "YunaCompact.SpeechVoice",
            "path": "Speech/Voices/YunaCompact.SpeechVoice"
          },
          {
            "value": 12,
            "name": "Zarvox.SpeechVoice",
            "path": "Speech/Voices/Zarvox.SpeechVoice"
          },
          {
            "value": 564,
            "name": "ZosiaCompact.SpeechVoice",
            "path": "Speech/Voices/ZosiaCompact.SpeechVoice"
          },
          {
            "value": 772,
            "name": "ZuzanaCompact.SpeechVoice",
            "path": "Speech/Voices/ZuzanaCompact.SpeechVoice"
          }
        ]
      }
    ]
  },
  {
    "value": 1060,
    "name": "Spelling",
    "path": "Spelling"
  },
  {
    "value": 412,
    "name": "Spotlight",
    "path": "Spotlight",
    "children": [
      {
        "value": 20,
        "name": "Application.mdimporter",
        "path": "Spotlight/Application.mdimporter",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "Spotlight/Application.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Archives.mdimporter",
        "path": "Spotlight/Archives.mdimporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Spotlight/Archives.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "Audio.mdimporter",
        "path": "Spotlight/Audio.mdimporter",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "Spotlight/Audio.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Automator.mdimporter",
        "path": "Spotlight/Automator.mdimporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Spotlight/Automator.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Bookmarks.mdimporter",
        "path": "Spotlight/Bookmarks.mdimporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Spotlight/Bookmarks.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "Chat.mdimporter",
        "path": "Spotlight/Chat.mdimporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "Spotlight/Chat.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "CoreMedia.mdimporter",
        "path": "Spotlight/CoreMedia.mdimporter",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "Spotlight/CoreMedia.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 32,
        "name": "Font.mdimporter",
        "path": "Spotlight/Font.mdimporter",
        "children": [
          {
            "value": 32,
            "name": "Contents",
            "path": "Spotlight/Font.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "iCal.mdimporter",
        "path": "Spotlight/iCal.mdimporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "Spotlight/iCal.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "Image.mdimporter",
        "path": "Spotlight/Image.mdimporter",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "Spotlight/Image.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 72,
        "name": "iPhoto.mdimporter",
        "path": "Spotlight/iPhoto.mdimporter",
        "children": [
          {
            "value": 72,
            "name": "Contents",
            "path": "Spotlight/iPhoto.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "iPhoto8.mdimporter",
        "path": "Spotlight/iPhoto8.mdimporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "Spotlight/iPhoto8.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "Mail.mdimporter",
        "path": "Spotlight/Mail.mdimporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Spotlight/Mail.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "MIDI.mdimporter",
        "path": "Spotlight/MIDI.mdimporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Spotlight/MIDI.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "Notes.mdimporter",
        "path": "Spotlight/Notes.mdimporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "Spotlight/Notes.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "PDF.mdimporter",
        "path": "Spotlight/PDF.mdimporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "Spotlight/PDF.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "PS.mdimporter",
        "path": "Spotlight/PS.mdimporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Spotlight/PS.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "QuartzComposer.mdimporter",
        "path": "Spotlight/QuartzComposer.mdimporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "Spotlight/QuartzComposer.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "RichText.mdimporter",
        "path": "Spotlight/RichText.mdimporter",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "Spotlight/RichText.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SystemPrefs.mdimporter",
        "path": "Spotlight/SystemPrefs.mdimporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "Spotlight/SystemPrefs.mdimporter/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "vCard.mdimporter",
        "path": "Spotlight/vCard.mdimporter",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "Spotlight/vCard.mdimporter/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 0,
    "name": "StartupItems",
    "path": "StartupItems"
  },
  {
    "value": 168,
    "name": "SyncServices",
    "path": "SyncServices",
    "children": [
      {
        "value": 0,
        "name": "AutoRegistration",
        "path": "SyncServices/AutoRegistration",
        "children": [
          {
            "value": 0,
            "name": "Clients",
            "path": "SyncServices/AutoRegistration/Clients"
          },
          {
            "value": 0,
            "name": "Schemas",
            "path": "SyncServices/AutoRegistration/Schemas"
          }
        ]
      },
      {
        "value": 168,
        "name": "Schemas",
        "path": "SyncServices/Schemas",
        "children": [
          {
            "value": 24,
            "name": "Bookmarks.syncschema",
            "path": "SyncServices/Schemas/Bookmarks.syncschema"
          },
          {
            "value": 68,
            "name": "Calendars.syncschema",
            "path": "SyncServices/Schemas/Calendars.syncschema"
          },
          {
            "value": 48,
            "name": "Contacts.syncschema",
            "path": "SyncServices/Schemas/Contacts.syncschema"
          },
          {
            "value": 16,
            "name": "Notes.syncschema",
            "path": "SyncServices/Schemas/Notes.syncschema"
          },
          {
            "value": 12,
            "name": "Palm.syncschema",
            "path": "SyncServices/Schemas/Palm.syncschema"
          }
        ]
      }
    ]
  },
  {
    "value": 3156,
    "name": "SystemConfiguration",
    "path": "SystemConfiguration",
    "children": [
      {
        "value": 8,
        "name": "ApplicationFirewallStartup.bundle",
        "path": "SystemConfiguration/ApplicationFirewallStartup.bundle",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemConfiguration/ApplicationFirewallStartup.bundle/Contents"
          }
        ]
      },
      {
        "value": 116,
        "name": "EAPOLController.bundle",
        "path": "SystemConfiguration/EAPOLController.bundle",
        "children": [
          {
            "value": 116,
            "name": "Contents",
            "path": "SystemConfiguration/EAPOLController.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "InterfaceNamer.bundle",
        "path": "SystemConfiguration/InterfaceNamer.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "SystemConfiguration/InterfaceNamer.bundle/Contents"
          }
        ]
      },
      {
        "value": 132,
        "name": "IPConfiguration.bundle",
        "path": "SystemConfiguration/IPConfiguration.bundle",
        "children": [
          {
            "value": 132,
            "name": "Contents",
            "path": "SystemConfiguration/IPConfiguration.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "IPMonitor.bundle",
        "path": "SystemConfiguration/IPMonitor.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "SystemConfiguration/IPMonitor.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "KernelEventMonitor.bundle",
        "path": "SystemConfiguration/KernelEventMonitor.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "SystemConfiguration/KernelEventMonitor.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "LinkConfiguration.bundle",
        "path": "SystemConfiguration/LinkConfiguration.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "SystemConfiguration/LinkConfiguration.bundle/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "Logger.bundle",
        "path": "SystemConfiguration/Logger.bundle",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "SystemConfiguration/Logger.bundle/Contents"
          }
        ]
      },
      {
        "value": 2804,
        "name": "PPPController.bundle",
        "path": "SystemConfiguration/PPPController.bundle",
        "children": [
          {
            "value": 2804,
            "name": "Contents",
            "path": "SystemConfiguration/PPPController.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "PreferencesMonitor.bundle",
        "path": "SystemConfiguration/PreferencesMonitor.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "SystemConfiguration/PreferencesMonitor.bundle/Contents"
          }
        ]
      },
      {
        "value": 76,
        "name": "PrinterNotifications.bundle",
        "path": "SystemConfiguration/PrinterNotifications.bundle",
        "children": [
          {
            "value": 76,
            "name": "Contents",
            "path": "SystemConfiguration/PrinterNotifications.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "SCNetworkReachability.bundle",
        "path": "SystemConfiguration/SCNetworkReachability.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "SystemConfiguration/SCNetworkReachability.bundle/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 1520,
    "name": "SystemProfiler",
    "path": "SystemProfiler",
    "children": [
      {
        "value": 84,
        "name": "SPAirPortReporter.spreporter",
        "path": "SystemProfiler/SPAirPortReporter.spreporter",
        "children": [
          {
            "value": 84,
            "name": "Contents",
            "path": "SystemProfiler/SPAirPortReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPApplicationsReporter.spreporter",
        "path": "SystemProfiler/SPApplicationsReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPApplicationsReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "SPAudioReporter.spreporter",
        "path": "SystemProfiler/SPAudioReporter.spreporter",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "SystemProfiler/SPAudioReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPBluetoothReporter.spreporter",
        "path": "SystemProfiler/SPBluetoothReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPBluetoothReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPCameraReporter.spreporter",
        "path": "SystemProfiler/SPCameraReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPCameraReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPCardReaderReporter.spreporter",
        "path": "SystemProfiler/SPCardReaderReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPCardReaderReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "SPComponentReporter.spreporter",
        "path": "SystemProfiler/SPComponentReporter.spreporter",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "SystemProfiler/SPComponentReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "SPConfigurationProfileReporter.spreporter",
        "path": "SystemProfiler/SPConfigurationProfileReporter.spreporter",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "SystemProfiler/SPConfigurationProfileReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPDeveloperToolsReporter.spreporter",
        "path": "SystemProfiler/SPDeveloperToolsReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPDeveloperToolsReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPDiagnosticsReporter.spreporter",
        "path": "SystemProfiler/SPDiagnosticsReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPDiagnosticsReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPDisabledApplicationsReporter.spreporter",
        "path": "SystemProfiler/SPDisabledApplicationsReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPDisabledApplicationsReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPDiscBurningReporter.spreporter",
        "path": "SystemProfiler/SPDiscBurningReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPDiscBurningReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 284,
        "name": "SPDisplaysReporter.spreporter",
        "path": "SystemProfiler/SPDisplaysReporter.spreporter",
        "children": [
          {
            "value": 284,
            "name": "Contents",
            "path": "SystemProfiler/SPDisplaysReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPEthernetReporter.spreporter",
        "path": "SystemProfiler/SPEthernetReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPEthernetReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPExtensionsReporter.spreporter",
        "path": "SystemProfiler/SPExtensionsReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPExtensionsReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPFibreChannelReporter.spreporter",
        "path": "SystemProfiler/SPFibreChannelReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPFibreChannelReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPFirewallReporter.spreporter",
        "path": "SystemProfiler/SPFirewallReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPFirewallReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPFireWireReporter.spreporter",
        "path": "SystemProfiler/SPFireWireReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPFireWireReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPFontReporter.spreporter",
        "path": "SystemProfiler/SPFontReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPFontReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPFrameworksReporter.spreporter",
        "path": "SystemProfiler/SPFrameworksReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPFrameworksReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPHardwareRAIDReporter.spreporter",
        "path": "SystemProfiler/SPHardwareRAIDReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPHardwareRAIDReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPInstallHistoryReporter.spreporter",
        "path": "SystemProfiler/SPInstallHistoryReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPInstallHistoryReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPLogsReporter.spreporter",
        "path": "SystemProfiler/SPLogsReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPLogsReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPManagedClientReporter.spreporter",
        "path": "SystemProfiler/SPManagedClientReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPManagedClientReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPMemoryReporter.spreporter",
        "path": "SystemProfiler/SPMemoryReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPMemoryReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 264,
        "name": "SPNetworkLocationReporter.spreporter",
        "path": "SystemProfiler/SPNetworkLocationReporter.spreporter",
        "children": [
          {
            "value": 264,
            "name": "Contents",
            "path": "SystemProfiler/SPNetworkLocationReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 268,
        "name": "SPNetworkReporter.spreporter",
        "path": "SystemProfiler/SPNetworkReporter.spreporter",
        "children": [
          {
            "value": 268,
            "name": "Contents",
            "path": "SystemProfiler/SPNetworkReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPNetworkVolumeReporter.spreporter",
        "path": "SystemProfiler/SPNetworkVolumeReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPNetworkVolumeReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPOSReporter.spreporter",
        "path": "SystemProfiler/SPOSReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPOSReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPParallelATAReporter.spreporter",
        "path": "SystemProfiler/SPParallelATAReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPParallelATAReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPParallelSCSIReporter.spreporter",
        "path": "SystemProfiler/SPParallelSCSIReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPParallelSCSIReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPPCIReporter.spreporter",
        "path": "SystemProfiler/SPPCIReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPPCIReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPPlatformReporter.spreporter",
        "path": "SystemProfiler/SPPlatformReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPPlatformReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPPowerReporter.spreporter",
        "path": "SystemProfiler/SPPowerReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPPowerReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPPrefPaneReporter.spreporter",
        "path": "SystemProfiler/SPPrefPaneReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPPrefPaneReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPPrintersReporter.spreporter",
        "path": "SystemProfiler/SPPrintersReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPPrintersReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPPrintersSoftwareReporter.spreporter",
        "path": "SystemProfiler/SPPrintersSoftwareReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPPrintersSoftwareReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPSASReporter.spreporter",
        "path": "SystemProfiler/SPSASReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPSASReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SPSerialATAReporter.spreporter",
        "path": "SystemProfiler/SPSerialATAReporter.spreporter",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "SystemProfiler/SPSerialATAReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPSPIReporter.spreporter",
        "path": "SystemProfiler/SPSPIReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPSPIReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPStartupItemReporter.spreporter",
        "path": "SystemProfiler/SPStartupItemReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPStartupItemReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPStorageReporter.spreporter",
        "path": "SystemProfiler/SPStorageReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPStorageReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "SPSyncReporter.spreporter",
        "path": "SystemProfiler/SPSyncReporter.spreporter",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "SystemProfiler/SPSyncReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "SPThunderboltReporter.spreporter",
        "path": "SystemProfiler/SPThunderboltReporter.spreporter",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "SystemProfiler/SPThunderboltReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "SPUniversalAccessReporter.spreporter",
        "path": "SystemProfiler/SPUniversalAccessReporter.spreporter",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "SystemProfiler/SPUniversalAccessReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 40,
        "name": "SPUSBReporter.spreporter",
        "path": "SystemProfiler/SPUSBReporter.spreporter",
        "children": [
          {
            "value": 40,
            "name": "Contents",
            "path": "SystemProfiler/SPUSBReporter.spreporter/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "SPWWANReporter.spreporter",
        "path": "SystemProfiler/SPWWANReporter.spreporter",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "SystemProfiler/SPWWANReporter.spreporter/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 9608,
    "name": "Tcl",
    "path": "Tcl",
    "children": [
      {
        "value": 3568,
        "name": "8.4",
        "path": "Tcl/8.4",
        "children": [
          {
            "value": 156,
            "name": "expect5.45",
            "path": "Tcl/8.4/expect5.45"
          },
          {
            "value": 28,
            "name": "Ffidl0.6.1",
            "path": "Tcl/8.4/Ffidl0.6.1"
          },
          {
            "value": 784,
            "name": "Img1.4",
            "path": "Tcl/8.4/Img1.4"
          },
          {
            "value": 88,
            "name": "itcl3.4",
            "path": "Tcl/8.4/itcl3.4"
          },
          {
            "value": 24,
            "name": "itk3.4",
            "path": "Tcl/8.4/itk3.4"
          },
          {
            "value": 28,
            "name": "Memchan2.2.1",
            "path": "Tcl/8.4/Memchan2.2.1"
          },
          {
            "value": 228,
            "name": "Mk4tcl2.4.9.7",
            "path": "Tcl/8.4/Mk4tcl2.4.9.7"
          },
          {
            "value": 96,
            "name": "QuickTimeTcl3.2",
            "path": "Tcl/8.4/QuickTimeTcl3.2"
          },
          {
            "value": 196,
            "name": "snack2.2",
            "path": "Tcl/8.4/snack2.2"
          },
          {
            "value": 24,
            "name": "tbcload1.7",
            "path": "Tcl/8.4/tbcload1.7"
          },
          {
            "value": 76,
            "name": "tclAE2.0.5",
            "path": "Tcl/8.4/tclAE2.0.5"
          },
          {
            "value": 20,
            "name": "Tclapplescript1.0",
            "path": "Tcl/8.4/Tclapplescript1.0"
          },
          {
            "value": 56,
            "name": "Tcldom2.6",
            "path": "Tcl/8.4/Tcldom2.6"
          },
          {
            "value": 56,
            "name": "tcldomxml2.6",
            "path": "Tcl/8.4/tcldomxml2.6"
          },
          {
            "value": 108,
            "name": "Tclexpat2.6",
            "path": "Tcl/8.4/Tclexpat2.6"
          },
          {
            "value": 16,
            "name": "Tclresource1.1.2",
            "path": "Tcl/8.4/Tclresource1.1.2"
          },
          {
            "value": 288,
            "name": "tclx8.4",
            "path": "Tcl/8.4/tclx8.4"
          },
          {
            "value": 60,
            "name": "Tclxml2.6",
            "path": "Tcl/8.4/Tclxml2.6"
          },
          {
            "value": 20,
            "name": "Tclxslt2.6",
            "path": "Tcl/8.4/Tclxslt2.6"
          },
          {
            "value": 396,
            "name": "tdom0.8.3",
            "path": "Tcl/8.4/tdom0.8.3"
          },
          {
            "value": 80,
            "name": "thread2.6.6",
            "path": "Tcl/8.4/thread2.6.6"
          },
          {
            "value": 68,
            "name": "Tktable2.10",
            "path": "Tcl/8.4/Tktable2.10"
          },
          {
            "value": 36,
            "name": "tls1.6.1",
            "path": "Tcl/8.4/tls1.6.1"
          },
          {
            "value": 32,
            "name": "tnc0.3.0",
            "path": "Tcl/8.4/tnc0.3.0"
          },
          {
            "value": 180,
            "name": "treectrl2.2.10",
            "path": "Tcl/8.4/treectrl2.2.10"
          },
          {
            "value": 120,
            "name": "Trf2.1.4",
            "path": "Tcl/8.4/Trf2.1.4"
          },
          {
            "value": 108,
            "name": "vfs1.4.1",
            "path": "Tcl/8.4/vfs1.4.1"
          },
          {
            "value": 196,
            "name": "xotcl1.6.6",
            "path": "Tcl/8.4/xotcl1.6.6"
          }
        ]
      },
      {
        "value": 3384,
        "name": "8.5",
        "path": "Tcl/8.5",
        "children": [
          {
            "value": 156,
            "name": "expect5.45",
            "path": "Tcl/8.5/expect5.45"
          },
          {
            "value": 32,
            "name": "Ffidl0.6.1",
            "path": "Tcl/8.5/Ffidl0.6.1"
          },
          {
            "value": 972,
            "name": "Img1.4",
            "path": "Tcl/8.5/Img1.4"
          },
          {
            "value": 88,
            "name": "itcl3.4",
            "path": "Tcl/8.5/itcl3.4"
          },
          {
            "value": 44,
            "name": "itk3.4",
            "path": "Tcl/8.5/itk3.4"
          },
          {
            "value": 32,
            "name": "Memchan2.2.1",
            "path": "Tcl/8.5/Memchan2.2.1"
          },
          {
            "value": 228,
            "name": "Mk4tcl2.4.9.7",
            "path": "Tcl/8.5/Mk4tcl2.4.9.7"
          },
          {
            "value": 24,
            "name": "tbcload1.7",
            "path": "Tcl/8.5/tbcload1.7"
          },
          {
            "value": 76,
            "name": "tclAE2.0.5",
            "path": "Tcl/8.5/tclAE2.0.5"
          },
          {
            "value": 56,
            "name": "Tcldom2.6",
            "path": "Tcl/8.5/Tcldom2.6"
          },
          {
            "value": 56,
            "name": "tcldomxml2.6",
            "path": "Tcl/8.5/tcldomxml2.6"
          },
          {
            "value": 108,
            "name": "Tclexpat2.6",
            "path": "Tcl/8.5/Tclexpat2.6"
          },
          {
            "value": 336,
            "name": "tclx8.4",
            "path": "Tcl/8.5/tclx8.4"
          },
          {
            "value": 60,
            "name": "Tclxml2.6",
            "path": "Tcl/8.5/Tclxml2.6"
          },
          {
            "value": 20,
            "name": "Tclxslt2.6",
            "path": "Tcl/8.5/Tclxslt2.6"
          },
          {
            "value": 400,
            "name": "tdom0.8.3",
            "path": "Tcl/8.5/tdom0.8.3"
          },
          {
            "value": 80,
            "name": "thread2.6.6",
            "path": "Tcl/8.5/thread2.6.6"
          },
          {
            "value": 124,
            "name": "Tktable2.10",
            "path": "Tcl/8.5/Tktable2.10"
          },
          {
            "value": 36,
            "name": "tls1.6.1",
            "path": "Tcl/8.5/tls1.6.1"
          },
          {
            "value": 32,
            "name": "tnc0.3.0",
            "path": "Tcl/8.5/tnc0.3.0"
          },
          {
            "value": 120,
            "name": "Trf2.1.4",
            "path": "Tcl/8.5/Trf2.1.4"
          },
          {
            "value": 108,
            "name": "vfs1.4.1",
            "path": "Tcl/8.5/vfs1.4.1"
          },
          {
            "value": 196,
            "name": "xotcl1.6.6",
            "path": "Tcl/8.5/xotcl1.6.6"
          }
        ]
      },
      {
        "value": 80,
        "name": "bin",
        "path": "Tcl/bin"
      },
      {
        "value": 224,
        "name": "bwidget1.9.1",
        "path": "Tcl/bwidget1.9.1",
        "children": [
          {
            "value": 100,
            "name": "images",
            "path": "Tcl/bwidget1.9.1/images"
          },
          {
            "value": 0,
            "name": "lang",
            "path": "Tcl/bwidget1.9.1/lang"
          }
        ]
      },
      {
        "value": 324,
        "name": "iwidgets4.0.2",
        "path": "Tcl/iwidgets4.0.2",
        "children": [
          {
            "value": 324,
            "name": "scripts",
            "path": "Tcl/iwidgets4.0.2/scripts"
          }
        ]
      },
      {
        "value": 40,
        "name": "sqlite3",
        "path": "Tcl/sqlite3"
      },
      {
        "value": 1456,
        "name": "tcllib1.12",
        "path": "Tcl/tcllib1.12",
        "children": [
          {
            "value": 8,
            "name": "aes",
            "path": "Tcl/tcllib1.12/aes"
          },
          {
            "value": 16,
            "name": "amazon-s3",
            "path": "Tcl/tcllib1.12/amazon-s3"
          },
          {
            "value": 12,
            "name": "asn",
            "path": "Tcl/tcllib1.12/asn"
          },
          {
            "value": 0,
            "name": "base32",
            "path": "Tcl/tcllib1.12/base32"
          },
          {
            "value": 0,
            "name": "base64",
            "path": "Tcl/tcllib1.12/base64"
          },
          {
            "value": 8,
            "name": "bee",
            "path": "Tcl/tcllib1.12/bee"
          },
          {
            "value": 16,
            "name": "bench",
            "path": "Tcl/tcllib1.12/bench"
          },
          {
            "value": 8,
            "name": "bibtex",
            "path": "Tcl/tcllib1.12/bibtex"
          },
          {
            "value": 12,
            "name": "blowfish",
            "path": "Tcl/tcllib1.12/blowfish"
          },
          {
            "value": 0,
            "name": "cache",
            "path": "Tcl/tcllib1.12/cache"
          },
          {
            "value": 8,
            "name": "cmdline",
            "path": "Tcl/tcllib1.12/cmdline"
          },
          {
            "value": 16,
            "name": "comm",
            "path": "Tcl/tcllib1.12/comm"
          },
          {
            "value": 0,
            "name": "control",
            "path": "Tcl/tcllib1.12/control"
          },
          {
            "value": 0,
            "name": "coroutine",
            "path": "Tcl/tcllib1.12/coroutine"
          },
          {
            "value": 12,
            "name": "counter",
            "path": "Tcl/tcllib1.12/counter"
          },
          {
            "value": 8,
            "name": "crc",
            "path": "Tcl/tcllib1.12/crc"
          },
          {
            "value": 8,
            "name": "csv",
            "path": "Tcl/tcllib1.12/csv"
          },
          {
            "value": 24,
            "name": "des",
            "path": "Tcl/tcllib1.12/des"
          },
          {
            "value": 36,
            "name": "dns",
            "path": "Tcl/tcllib1.12/dns"
          },
          {
            "value": 0,
            "name": "docstrip",
            "path": "Tcl/tcllib1.12/docstrip"
          },
          {
            "value": 44,
            "name": "doctools",
            "path": "Tcl/tcllib1.12/doctools"
          },
          {
            "value": 8,
            "name": "doctools2base",
            "path": "Tcl/tcllib1.12/doctools2base"
          },
          {
            "value": 12,
            "name": "doctools2idx",
            "path": "Tcl/tcllib1.12/doctools2idx"
          },
          {
            "value": 12,
            "name": "doctools2toc",
            "path": "Tcl/tcllib1.12/doctools2toc"
          },
          {
            "value": 36,
            "name": "fileutil",
            "path": "Tcl/tcllib1.12/fileutil"
          },
          {
            "value": 16,
            "name": "ftp",
            "path": "Tcl/tcllib1.12/ftp"
          },
          {
            "value": 16,
            "name": "ftpd",
            "path": "Tcl/tcllib1.12/ftpd"
          },
          {
            "value": 84,
            "name": "fumagic",
            "path": "Tcl/tcllib1.12/fumagic"
          },
          {
            "value": 0,
            "name": "gpx",
            "path": "Tcl/tcllib1.12/gpx"
          },
          {
            "value": 20,
            "name": "grammar_fa",
            "path": "Tcl/tcllib1.12/grammar_fa"
          },
          {
            "value": 8,
            "name": "grammar_me",
            "path": "Tcl/tcllib1.12/grammar_me"
          },
          {
            "value": 8,
            "name": "grammar_peg",
            "path": "Tcl/tcllib1.12/grammar_peg"
          },
          {
            "value": 12,
            "name": "html",
            "path": "Tcl/tcllib1.12/html"
          },
          {
            "value": 12,
            "name": "htmlparse",
            "path": "Tcl/tcllib1.12/htmlparse"
          },
          {
            "value": 8,
            "name": "http",
            "path": "Tcl/tcllib1.12/http"
          },
          {
            "value": 0,
            "name": "ident",
            "path": "Tcl/tcllib1.12/ident"
          },
          {
            "value": 12,
            "name": "imap4",
            "path": "Tcl/tcllib1.12/imap4"
          },
          {
            "value": 0,
            "name": "inifile",
            "path": "Tcl/tcllib1.12/inifile"
          },
          {
            "value": 0,
            "name": "interp",
            "path": "Tcl/tcllib1.12/interp"
          },
          {
            "value": 0,
            "name": "irc",
            "path": "Tcl/tcllib1.12/irc"
          },
          {
            "value": 0,
            "name": "javascript",
            "path": "Tcl/tcllib1.12/javascript"
          },
          {
            "value": 12,
            "name": "jpeg",
            "path": "Tcl/tcllib1.12/jpeg"
          },
          {
            "value": 0,
            "name": "json",
            "path": "Tcl/tcllib1.12/json"
          },
          {
            "value": 28,
            "name": "ldap",
            "path": "Tcl/tcllib1.12/ldap"
          },
          {
            "value": 20,
            "name": "log",
            "path": "Tcl/tcllib1.12/log"
          },
          {
            "value": 0,
            "name": "map",
            "path": "Tcl/tcllib1.12/map"
          },
          {
            "value": 12,
            "name": "mapproj",
            "path": "Tcl/tcllib1.12/mapproj"
          },
          {
            "value": 140,
            "name": "math",
            "path": "Tcl/tcllib1.12/math"
          },
          {
            "value": 8,
            "name": "md4",
            "path": "Tcl/tcllib1.12/md4"
          },
          {
            "value": 16,
            "name": "md5",
            "path": "Tcl/tcllib1.12/md5"
          },
          {
            "value": 0,
            "name": "md5crypt",
            "path": "Tcl/tcllib1.12/md5crypt"
          },
          {
            "value": 36,
            "name": "mime",
            "path": "Tcl/tcllib1.12/mime"
          },
          {
            "value": 0,
            "name": "multiplexer",
            "path": "Tcl/tcllib1.12/multiplexer"
          },
          {
            "value": 0,
            "name": "namespacex",
            "path": "Tcl/tcllib1.12/namespacex"
          },
          {
            "value": 12,
            "name": "ncgi",
            "path": "Tcl/tcllib1.12/ncgi"
          },
          {
            "value": 0,
            "name": "nmea",
            "path": "Tcl/tcllib1.12/nmea"
          },
          {
            "value": 8,
            "name": "nns",
            "path": "Tcl/tcllib1.12/nns"
          },
          {
            "value": 8,
            "name": "nntp",
            "path": "Tcl/tcllib1.12/nntp"
          },
          {
            "value": 0,
            "name": "ntp",
            "path": "Tcl/tcllib1.12/ntp"
          },
          {
            "value": 8,
            "name": "otp",
            "path": "Tcl/tcllib1.12/otp"
          },
          {
            "value": 48,
            "name": "page",
            "path": "Tcl/tcllib1.12/page"
          },
          {
            "value": 0,
            "name": "pluginmgr",
            "path": "Tcl/tcllib1.12/pluginmgr"
          },
          {
            "value": 0,
            "name": "png",
            "path": "Tcl/tcllib1.12/png"
          },
          {
            "value": 8,
            "name": "pop3",
            "path": "Tcl/tcllib1.12/pop3"
          },
          {
            "value": 8,
            "name": "pop3d",
            "path": "Tcl/tcllib1.12/pop3d"
          },
          {
            "value": 8,
            "name": "profiler",
            "path": "Tcl/tcllib1.12/profiler"
          },
          {
            "value": 72,
            "name": "pt",
            "path": "Tcl/tcllib1.12/pt"
          },
          {
            "value": 0,
            "name": "rc4",
            "path": "Tcl/tcllib1.12/rc4"
          },
          {
            "value": 0,
            "name": "rcs",
            "path": "Tcl/tcllib1.12/rcs"
          },
          {
            "value": 12,
            "name": "report",
            "path": "Tcl/tcllib1.12/report"
          },
          {
            "value": 8,
            "name": "rest",
            "path": "Tcl/tcllib1.12/rest"
          },
          {
            "value": 16,
            "name": "ripemd",
            "path": "Tcl/tcllib1.12/ripemd"
          },
          {
            "value": 8,
            "name": "sasl",
            "path": "Tcl/tcllib1.12/sasl"
          },
          {
            "value": 24,
            "name": "sha1",
            "path": "Tcl/tcllib1.12/sha1"
          },
          {
            "value": 0,
            "name": "simulation",
            "path": "Tcl/tcllib1.12/simulation"
          },
          {
            "value": 8,
            "name": "smtpd",
            "path": "Tcl/tcllib1.12/smtpd"
          },
          {
            "value": 84,
            "name": "snit",
            "path": "Tcl/tcllib1.12/snit"
          },
          {
            "value": 0,
            "name": "soundex",
            "path": "Tcl/tcllib1.12/soundex"
          },
          {
            "value": 12,
            "name": "stooop",
            "path": "Tcl/tcllib1.12/stooop"
          },
          {
            "value": 48,
            "name": "stringprep",
            "path": "Tcl/tcllib1.12/stringprep"
          },
          {
            "value": 156,
            "name": "struct",
            "path": "Tcl/tcllib1.12/struct"
          },
          {
            "value": 0,
            "name": "tar",
            "path": "Tcl/tcllib1.12/tar"
          },
          {
            "value": 24,
            "name": "tepam",
            "path": "Tcl/tcllib1.12/tepam"
          },
          {
            "value": 0,
            "name": "term",
            "path": "Tcl/tcllib1.12/term"
          },
          {
            "value": 52,
            "name": "textutil",
            "path": "Tcl/tcllib1.12/textutil"
          },
          {
            "value": 0,
            "name": "tie",
            "path": "Tcl/tcllib1.12/tie"
          },
          {
            "value": 8,
            "name": "tiff",
            "path": "Tcl/tcllib1.12/tiff"
          },
          {
            "value": 0,
            "name": "transfer",
            "path": "Tcl/tcllib1.12/transfer"
          },
          {
            "value": 0,
            "name": "treeql",
            "path": "Tcl/tcllib1.12/treeql"
          },
          {
            "value": 0,
            "name": "uev",
            "path": "Tcl/tcllib1.12/uev"
          },
          {
            "value": 8,
            "name": "units",
            "path": "Tcl/tcllib1.12/units"
          },
          {
            "value": 8,
            "name": "uri",
            "path": "Tcl/tcllib1.12/uri"
          },
          {
            "value": 0,
            "name": "uuid",
            "path": "Tcl/tcllib1.12/uuid"
          },
          {
            "value": 0,
            "name": "virtchannel_base",
            "path": "Tcl/tcllib1.12/virtchannel_base"
          },
          {
            "value": 0,
            "name": "virtchannel_core",
            "path": "Tcl/tcllib1.12/virtchannel_core"
          },
          {
            "value": 0,
            "name": "virtchannel_transform",
            "path": "Tcl/tcllib1.12/virtchannel_transform"
          },
          {
            "value": 16,
            "name": "wip",
            "path": "Tcl/tcllib1.12/wip"
          },
          {
            "value": 12,
            "name": "yaml",
            "path": "Tcl/tcllib1.12/yaml"
          }
        ]
      },
      {
        "value": 60,
        "name": "tclsoap1.6.8",
        "path": "Tcl/tclsoap1.6.8",
        "children": [
          {
            "value": 0,
            "name": "interop",
            "path": "Tcl/tclsoap1.6.8/interop"
          }
        ]
      },
      {
        "value": 56,
        "name": "tkcon2.6",
        "path": "Tcl/tkcon2.6"
      },
      {
        "value": 412,
        "name": "tklib0.5",
        "path": "Tcl/tklib0.5",
        "children": [
          {
            "value": 0,
            "name": "autoscroll",
            "path": "Tcl/tklib0.5/autoscroll"
          },
          {
            "value": 8,
            "name": "canvas",
            "path": "Tcl/tklib0.5/canvas"
          },
          {
            "value": 8,
            "name": "chatwidget",
            "path": "Tcl/tklib0.5/chatwidget"
          },
          {
            "value": 28,
            "name": "controlwidget",
            "path": "Tcl/tklib0.5/controlwidget"
          },
          {
            "value": 0,
            "name": "crosshair",
            "path": "Tcl/tklib0.5/crosshair"
          },
          {
            "value": 8,
            "name": "ctext",
            "path": "Tcl/tklib0.5/ctext"
          },
          {
            "value": 0,
            "name": "cursor",
            "path": "Tcl/tklib0.5/cursor"
          },
          {
            "value": 0,
            "name": "datefield",
            "path": "Tcl/tklib0.5/datefield"
          },
          {
            "value": 24,
            "name": "diagrams",
            "path": "Tcl/tklib0.5/diagrams"
          },
          {
            "value": 0,
            "name": "getstring",
            "path": "Tcl/tklib0.5/getstring"
          },
          {
            "value": 0,
            "name": "history",
            "path": "Tcl/tklib0.5/history"
          },
          {
            "value": 24,
            "name": "ico",
            "path": "Tcl/tklib0.5/ico"
          },
          {
            "value": 8,
            "name": "ipentry",
            "path": "Tcl/tklib0.5/ipentry"
          },
          {
            "value": 16,
            "name": "khim",
            "path": "Tcl/tklib0.5/khim"
          },
          {
            "value": 20,
            "name": "menubar",
            "path": "Tcl/tklib0.5/menubar"
          },
          {
            "value": 16,
            "name": "ntext",
            "path": "Tcl/tklib0.5/ntext"
          },
          {
            "value": 48,
            "name": "plotchart",
            "path": "Tcl/tklib0.5/plotchart"
          },
          {
            "value": 8,
            "name": "style",
            "path": "Tcl/tklib0.5/style"
          },
          {
            "value": 0,
            "name": "swaplist",
            "path": "Tcl/tklib0.5/swaplist"
          },
          {
            "value": 148,
            "name": "tablelist",
            "path": "Tcl/tklib0.5/tablelist"
          },
          {
            "value": 8,
            "name": "tkpiechart",
            "path": "Tcl/tklib0.5/tkpiechart"
          },
          {
            "value": 8,
            "name": "tooltip",
            "path": "Tcl/tklib0.5/tooltip"
          },
          {
            "value": 32,
            "name": "widget",
            "path": "Tcl/tklib0.5/widget"
          }
        ]
      }
    ]
  },
  {
    "value": 80,
    "name": "TextEncodings",
    "path": "TextEncodings",
    "children": [
      {
        "value": 0,
        "name": "ArabicEncodings.bundle",
        "path": "TextEncodings/ArabicEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/ArabicEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "CentralEuropean Encodings.bundle",
        "path": "TextEncodings/CentralEuropean Encodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/CentralEuropean Encodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "ChineseEncodings Supplement.bundle",
        "path": "TextEncodings/ChineseEncodings Supplement.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/ChineseEncodings Supplement.bundle/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "ChineseEncodings.bundle",
        "path": "TextEncodings/ChineseEncodings.bundle",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "TextEncodings/ChineseEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "CoreEncodings.bundle",
        "path": "TextEncodings/CoreEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/CoreEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "CyrillicEncodings.bundle",
        "path": "TextEncodings/CyrillicEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/CyrillicEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "GreekEncodings.bundle",
        "path": "TextEncodings/GreekEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/GreekEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "HebrewEncodings.bundle",
        "path": "TextEncodings/HebrewEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/HebrewEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "IndicEncodings.bundle",
        "path": "TextEncodings/IndicEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/IndicEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "JapaneseEncodings.bundle",
        "path": "TextEncodings/JapaneseEncodings.bundle",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "TextEncodings/JapaneseEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "KoreanEncodings.bundle",
        "path": "TextEncodings/KoreanEncodings.bundle",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "TextEncodings/KoreanEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "SymbolEncodings.bundle",
        "path": "TextEncodings/SymbolEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/SymbolEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "ThaiEncodings.bundle",
        "path": "TextEncodings/ThaiEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/ThaiEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "TurkishEncodings.bundle",
        "path": "TextEncodings/TurkishEncodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/TurkishEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "UnicodeEncodings.bundle",
        "path": "TextEncodings/UnicodeEncodings.bundle",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "TextEncodings/UnicodeEncodings.bundle/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "WesternLanguage Encodings.bundle",
        "path": "TextEncodings/WesternLanguage Encodings.bundle",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "TextEncodings/WesternLanguage Encodings.bundle/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 600,
    "name": "UserEventPlugins",
    "path": "UserEventPlugins",
    "children": [
      {
        "value": 60,
        "name": "ACRRDaemon.plugin",
        "path": "UserEventPlugins/ACRRDaemon.plugin",
        "children": [
          {
            "value": 60,
            "name": "Contents",
            "path": "UserEventPlugins/ACRRDaemon.plugin/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "AirPortUserAgent.plugin",
        "path": "UserEventPlugins/AirPortUserAgent.plugin",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "UserEventPlugins/AirPortUserAgent.plugin/Contents"
          }
        ]
      },
      {
        "value": 0,
        "name": "alfUIplugin.plugin",
        "path": "UserEventPlugins/alfUIplugin.plugin",
        "children": [
          {
            "value": 0,
            "name": "Contents",
            "path": "UserEventPlugins/alfUIplugin.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "AppleHIDMouseAgent.plugin",
        "path": "UserEventPlugins/AppleHIDMouseAgent.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/AppleHIDMouseAgent.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "AssistantUEA.plugin",
        "path": "UserEventPlugins/AssistantUEA.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/AssistantUEA.plugin/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "AutoTimeZone.plugin",
        "path": "UserEventPlugins/AutoTimeZone.plugin",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "UserEventPlugins/AutoTimeZone.plugin/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "BluetoothUserAgent-Plugin.plugin",
        "path": "UserEventPlugins/BluetoothUserAgent-Plugin.plugin",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "UserEventPlugins/BluetoothUserAgent-Plugin.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "BonjourEvents.plugin",
        "path": "UserEventPlugins/BonjourEvents.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/BonjourEvents.plugin/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "BTMMPortInUseAgent.plugin",
        "path": "UserEventPlugins/BTMMPortInUseAgent.plugin",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "UserEventPlugins/BTMMPortInUseAgent.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "CalendarMonitor.plugin",
        "path": "UserEventPlugins/CalendarMonitor.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/CalendarMonitor.plugin/Contents"
          }
        ]
      },
      {
        "value": 88,
        "name": "CaptiveSystemAgent.plugin",
        "path": "UserEventPlugins/CaptiveSystemAgent.plugin",
        "children": [
          {
            "value": 88,
            "name": "Contents",
            "path": "UserEventPlugins/CaptiveSystemAgent.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "CaptiveUserAgent.plugin",
        "path": "UserEventPlugins/CaptiveUserAgent.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/CaptiveUserAgent.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.bonjour.plugin",
        "path": "UserEventPlugins/com.apple.bonjour.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.bonjour.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.cfnotification.plugin",
        "path": "UserEventPlugins/com.apple.cfnotification.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.cfnotification.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.diskarbitration.plugin",
        "path": "UserEventPlugins/com.apple.diskarbitration.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.diskarbitration.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.dispatch.vfs.plugin",
        "path": "UserEventPlugins/com.apple.dispatch.vfs.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.dispatch.vfs.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "com.apple.fsevents.matching.plugin",
        "path": "UserEventPlugins/com.apple.fsevents.matching.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.fsevents.matching.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.iokit.matching.plugin",
        "path": "UserEventPlugins/com.apple.iokit.matching.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.iokit.matching.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.KeyStore.plugin",
        "path": "UserEventPlugins/com.apple.KeyStore.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.KeyStore.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.launchd.helper.plugin",
        "path": "UserEventPlugins/com.apple.launchd.helper.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.launchd.helper.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.locationd.events.plugin",
        "path": "UserEventPlugins/com.apple.locationd.events.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.locationd.events.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.notifyd.matching.plugin",
        "path": "UserEventPlugins/com.apple.notifyd.matching.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.notifyd.matching.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.opendirectory.matching.plugin",
        "path": "UserEventPlugins/com.apple.opendirectory.matching.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.opendirectory.matching.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "com.apple.rcdevent.matching.plugin",
        "path": "UserEventPlugins/com.apple.rcdevent.matching.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.rcdevent.matching.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.reachability.plugin",
        "path": "UserEventPlugins/com.apple.reachability.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.reachability.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.systemconfiguration.plugin",
        "path": "UserEventPlugins/com.apple.systemconfiguration.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.systemconfiguration.plugin/Contents"
          }
        ]
      },
      {
        "value": 44,
        "name": "com.apple.telemetry.plugin",
        "path": "UserEventPlugins/com.apple.telemetry.plugin",
        "children": [
          {
            "value": 44,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.telemetry.plugin/Contents"
          }
        ]
      },
      {
        "value": 24,
        "name": "com.apple.time.plugin",
        "path": "UserEventPlugins/com.apple.time.plugin",
        "children": [
          {
            "value": 24,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.time.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "com.apple.TimeMachine.plugin",
        "path": "UserEventPlugins/com.apple.TimeMachine.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.TimeMachine.plugin/Contents"
          }
        ]
      },
      {
        "value": 20,
        "name": "com.apple.TimeMachine.System.plugin",
        "path": "UserEventPlugins/com.apple.TimeMachine.System.plugin",
        "children": [
          {
            "value": 20,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.TimeMachine.System.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "com.apple.universalaccess.events.plugin",
        "path": "UserEventPlugins/com.apple.universalaccess.events.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.universalaccess.events.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "com.apple.usernotificationcenter.matching.plugin",
        "path": "UserEventPlugins/com.apple.usernotificationcenter.matching.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.usernotificationcenter.matching.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "com.apple.WorkstationService.plugin",
        "path": "UserEventPlugins/com.apple.WorkstationService.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/com.apple.WorkstationService.plugin/Contents"
          }
        ]
      },
      {
        "value": 28,
        "name": "EAPOLMonitor.plugin",
        "path": "UserEventPlugins/EAPOLMonitor.plugin",
        "children": [
          {
            "value": 28,
            "name": "Contents",
            "path": "UserEventPlugins/EAPOLMonitor.plugin/Contents"
          }
        ]
      },
      {
        "value": 8,
        "name": "GSSNotificationForwarder.plugin",
        "path": "UserEventPlugins/GSSNotificationForwarder.plugin",
        "children": [
          {
            "value": 8,
            "name": "Contents",
            "path": "UserEventPlugins/GSSNotificationForwarder.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "LocationMenu.plugin",
        "path": "UserEventPlugins/LocationMenu.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/LocationMenu.plugin/Contents"
          }
        ]
      },
      {
        "value": 12,
        "name": "PrinterMonitor.plugin",
        "path": "UserEventPlugins/PrinterMonitor.plugin",
        "children": [
          {
            "value": 12,
            "name": "Contents",
            "path": "UserEventPlugins/PrinterMonitor.plugin/Contents"
          }
        ]
      },
      {
        "value": 16,
        "name": "SCMonitor.plugin",
        "path": "UserEventPlugins/SCMonitor.plugin",
        "children": [
          {
            "value": 16,
            "name": "Contents",
            "path": "UserEventPlugins/SCMonitor.plugin/Contents"
          }
        ]
      }
    ]
  },
  {
    "value": 536,
    "name": "Video",
    "path": "Video",
    "children": [
      {
        "value": 536,
        "name": "Plug-Ins",
        "path": "Video/Plug-Ins",
        "children": [
          {
            "value": 536,
            "name": "AppleProResCodec.bundle",
            "path": "Video/Plug-Ins/AppleProResCodec.bundle"
          }
        ]
      }
    ]
  },
  {
    "value": 272,
    "name": "WidgetResources",
    "path": "WidgetResources",
    "children": [
      {
        "value": 16,
        "name": ".parsers",
        "path": "WidgetResources/.parsers"
      },
      {
        "value": 172,
        "name": "AppleClasses",
        "path": "WidgetResources/AppleClasses",
        "children": [
          {
            "value": 156,
            "name": "Images",
            "path": "WidgetResources/AppleClasses/Images"
          }
        ]
      },
      {
        "value": 0,
        "name": "AppleParser",
        "path": "WidgetResources/AppleParser"
      },
      {
        "value": 48,
        "name": "button",
        "path": "WidgetResources/button"
      },
      {
        "value": 32,
        "name": "ibutton",
        "path": "WidgetResources/ibutton"
      }
    ]
  }
];
myChart.hideLoading();
  function getLevelOption() {
    return [
      {
        itemStyle: {
          borderColor: '#777',
          borderWidth: 0,
          gapWidth: 1
        },
        upperLabel: {
          show: false
        }
      },
      {
        itemStyle: {
          borderColor: '#555',
          borderWidth: 5,
          gapWidth: 1
        },
        emphasis: {
          itemStyle: {
            borderColor: '#ddd'
          }
        }
      },
      {
        colorSaturation: [0.35, 0.5],
        itemStyle: {
          borderWidth: 5,
          gapWidth: 1,
          borderColorSaturation: 0.6
        }
      }
    ];
  }
  myChart.setOption(
    (option = {
      title: {
        text: 'Disk Usage',
        left: 'center'
      },
      tooltip: {
        formatter: function (info) {
          var value = info.value;
          var treePathInfo = info.treePathInfo;
          var treePath = [];
          for (var i = 1; i < treePathInfo.length; i++) {
            treePath.push(treePathInfo[i].name);
          }
          return [
            '<div class="tooltip-title">' +
              echarts.format.encodeHTML(treePath.join('/')) +
              '</div>',
            'Disk Usage: ' + echarts.format.addCommas(value) + ' KB'
          ].join('');
        }
      },
      series: [
        {
          name: 'Disk Usage',
          type: 'treemap',
          visibleMin: 300,
          label: {
            show: true,
            formatter: '{b}'
          },
          upperLabel: {
            show: true,
            height: 30
          },
          itemStyle: {
            borderColor: '#fff'
          },
          levels: getLevelOption(),
          data: diskData
        }
      ]
    })
  );

      // ... (112 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (9 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (46 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (37 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (32 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (24 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (21 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (20 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (14 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (15 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (15 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (14 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (12 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (11 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
      // ... (14 total entries — truncated, keep first 8 as sample. Agent: query DuckDB)
        ]
```
