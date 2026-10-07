# Java 集合框架速览

## HashMap 的 key 相等判定

HashMap 判断两个 key 是否相等的必要且充分条件是：key 的 hashCode() 相等且 equals() 返回 true。执行顺序是先比较 hashCode（定位桶，速度快、过滤掉绝大多数不相等的 key），哈希冲突时才继续调用 equals。这也是重写 equals 必须重写 hashCode 的原因——两者是配合工作的约定。

## HashSet 与 HashMap 的关系

HashSet 的底层由 HashMap 实现：HashSet 只使用 HashMap 的键，值统一由一个固定的 Object 常量填充，因此 HashSet 的元素唯一性、无序性都由 HashMap 的 key 机制保证。add 返回 false 即表示元素已存在。

## 集合框架的体系结构

Java 集合框架分两大接口族：Collection 与 Map。Collection 下有 List（ArrayList、LinkedList 等，有序可重复）、Set（HashSet、TreeSet 等，不重复）与 Queue；Map 独立成族（HashMap、TreeMap 等，键值对）。List 家族常用 ArrayList 做随机访问、LinkedList 做频繁头尾增删；Map 家族以 HashMap 为通用选择。
