# Java 并发编程速览

## synchronized 的锁状态

synchronized 在 JVM 中的锁状态共四种：无锁状态、偏向锁、轻量级锁、重量级锁。锁会随竞争情况升级：只有一个线程访问时偏向锁记录线程 ID；出现轻度竞争时膨胀为轻量级锁（CAS 自旋）；竞争激烈时升级为重量级锁（依赖操作系统互斥量，线程阻塞）。锁升级不可逆。

## CAS 及其缺陷

CAS（Compare And Swap）是 CPU 提供的原子操作：比较内存值与预期值，相等则写入新值。它能以无锁方式实现原子更新（AtomicInteger 等的基础）。主要缺陷：ABA 问题（值被改回原样，可用版本号或时间戳解决）、失败时自旋开销大（竞争激烈时 CPU 空转）、只能保证单个变量的原子性，无法覆盖多个变量的复合操作。

## 核心锁机制与并发工具

Java 并发编程的核心锁机制与工具包括：synchronized（JVM 内置监视器锁，使用简单、自动释放）、ReentrantLock（支持可中断获取、可轮询、可超时与公平锁）、读写锁 ReentrantReadWriteLock、StampedLock（乐观读），以及 AQS（AbstractQueuedSynchronizer）同步器框架——ReentrantLock、Semaphore、CountDownLatch 等均基于 AQS 实现，通过状态位与 FIFO 等待队列管理同步。
