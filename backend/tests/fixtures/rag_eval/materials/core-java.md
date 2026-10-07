# Java 核心基础速览

面向面试复习的 Java 基础要点整理，覆盖语言基础、集合、并发与虚拟机四部分中的常见考点。本文档为文字型语料，配套表格与含图语料见 `collections.md`、`lock-comparison.csv`、`collection-complexity.xlsx` 与 `jvm-architecture.xlsx`。

## JDK、JRE 与 JVM 的关系

JDK 是 Java 开发工具包，包含 JRE 以及编译器、调试器等开发工具；JRE 是 Java 运行时环境，包含运行 Java 程序所需的类库与 JVM；JVM 是执行字节码的虚拟机。三者为包含关系：JDK 包含 JRE，JRE 包含 JVM。安装 JDK 之后即可编译并运行 Java 程序，实现「一次编写，到处运行」。

## int 与 Integer 的关系

int 是基本数据类型，变量直接存值；Integer 是 int 的包装类，属于引用数据类型，实例是对象。Integer 内部维护一个静态缓存池：通过 `Integer.valueOf` 装箱时，-128 到 127 之间的数值会复用缓存对象，因此 `Integer.valueOf(100) == Integer.valueOf(100)` 为 true；超出该范围的两个包装对象即使数值相等也不相等，比较数值应使用 equals。

## 装箱与拆箱

装箱是基本类型转换为包装类（如 int 转为 Integer），拆箱是包装类转换为基本类型。编译器在赋值、方法调用等场合会自动插入 `Integer.valueOf` 与 `intValue()`，即自动装箱与自动拆箱。需要注意：包装类型为 null 时自动拆箱会抛出 NullPointerException。装箱与拆箱是互逆操作。

## String、StringBuffer 与 StringBuilder

String 是不可变的：任何修改都会创建新对象。StringBuffer 可变且线程安全，其方法以 synchronized 修饰，适合多线程环境；StringBuilder 可变但不是线程安全的，单线程下性能更高。频繁拼接字符串时应优先使用 StringBuilder。

## equals 与 hashCode 的约定

Object 的默认 equals 与 hashCode 都基于内存地址。重写 equals 改为按内容比较之后，必须同步重写 hashCode：相等的两个对象必须有相同的哈希值，哈希容器（如 HashMap 定位桶）依赖这一约定；否则相等对象会被散落到不同的桶，导致查找与去重失效。

## 面向对象与三大特性

封装、继承、多态构成面向对象的三大特性。封装隐藏内部实现、只暴露接口；继承复用父类的结构与行为；多态让同一接口在不同对象上表现出不同的实现。三者共同构成面向对象程序设计的基础。

## 多态的实现原理

多态通过动态绑定（后期绑定）实现：运行时根据对象的实际类型选择方法版本，而不是按引用变量的静态类型。常见体现为方法重载（编译期确定）、方法重写、接口与实现。JVM 通过方法表等机制在运行时完成虚方法的派发。

## 泛型与类型安全

泛型把类型参数化，让编译器在编译期检查类型一致性，避免运行期的强制类型转换与 ClassCastException，主要用于提高代码的类型安全。泛型信息在编译后被擦除（类型擦除），运行期还原为原始类型。
