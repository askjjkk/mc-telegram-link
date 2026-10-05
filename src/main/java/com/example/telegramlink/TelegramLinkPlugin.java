package com.example.telegramlink;

import org.bukkit.Bukkit;
import org.bukkit.ChatColor;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.AsyncPlayerChatEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitRunnable;

import java.security.SecureRandom;
import java.sql.*;

public class TelegramLinkPlugin extends JavaPlugin implements CommandExecutor, Listener {

    private Connection connection;

    private final String DB_HOST = "ep-delicate-sun-b1x8znjr-pooler.c-5.eu-central-1.aws.neon.tech";
    private final int DB_PORT = 5432;
    private final String DB_NAME = "neondb";
    private final String DB_USER = "neondb_owner";
    private final String DB_PASS = "npg_20wOVsdFEUmg";

    @Override
    public void onEnable() {
        saveDefaultConfig();
        initDatabase();

        if (getCommand("link") != null) {
            getCommand("link").setExecutor(this);
        }

        getServer().getPluginManager().registerEvents(this, this);
        startCommandPollTask();

        getLogger().info("=========================================");
        getLogger().info(" TelegramLink v1.0.0 успешно подключен к PostgreSQL!");
        getLogger().info("=========================================");
    }

    @Override
    public void onDisable() {
        closeDatabase();
    }

    private synchronized Connection getConnection() throws SQLException {
        if (connection == null || connection.isClosed()) {
            String url = "jdbc:postgresql://" + DB_HOST + ":" + DB_PORT + "/" + DB_NAME + "?sslmode=require";
            connection = DriverManager.getConnection(url, DB_USER, DB_PASS);
        }
        return connection;
    }

    private void initDatabase() {
        try (Statement stmt = getConnection().createStatement()) {
            stmt.execute("CREATE TABLE IF NOT EXISTS pending_codes (code VARCHAR(6) PRIMARY KEY, uuid VARCHAR(36) NOT NULL, expires_at BIGINT NOT NULL);");
            stmt.execute("CREATE TABLE IF NOT EXISTS linked_players (uuid VARCHAR(36) PRIMARY KEY, telegram_id BIGINT NOT NULL, created_at BIGINT NOT NULL);");
            stmt.execute("CREATE TABLE IF NOT EXISTS settings (key VARCHAR(50) PRIMARY KEY, value TEXT NOT NULL);");
            stmt.execute("CREATE TABLE IF NOT EXISTS admins (telegram_id BIGINT PRIMARY KEY, created_at BIGINT NOT NULL);");
            stmt.execute("CREATE TABLE IF NOT EXISTS chat_messages (id SERIAL PRIMARY KEY, player_name VARCHAR(32) NOT NULL, message TEXT NOT NULL, sent INT DEFAULT 0);");
            stmt.execute("CREATE TABLE IF NOT EXISTS pending_commands (id SERIAL PRIMARY KEY, command TEXT NOT NULL);");
        } catch (SQLException e) {
            getLogger().severe("Ошибка инициализации PostgreSQL: " + e.getMessage());
        }
    }

    private void closeDatabase() {
        try {
            if (connection != null && !connection.isClosed()) {
                connection.close();
            }
        } catch (SQLException e) {
            e.printStackTrace();
        }
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPlayerChat(AsyncPlayerChatEvent event) {
        String playerName = event.getPlayer().getName();
        String message = event.getMessage();

        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            try {
                Connection conn = getConnection();
                String sql = "INSERT INTO chat_messages (player_name, message, sent) VALUES (?, ?, 0)";
                try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                    pstmt.setString(1, playerName);
                    pstmt.setString(2, message);
                    pstmt.executeUpdate();
                }
            } catch (SQLException e) {
                e.printStackTrace();
            }
        });
    }

    private void startCommandPollTask() {
        new BukkitRunnable() {
            @Override
            public void run() {
                try {
                    Connection conn = getConnection();
                    String selectSql = "SELECT id, command FROM pending_commands";
                    try (Statement stmt = conn.createStatement();
                         ResultSet rs = stmt.executeQuery(selectSql)) {

                        while (rs.next()) {
                            int id = rs.getInt("id");
                            String cmd = rs.getString("command");

                            Bukkit.dispatchCommand(Bukkit.getConsoleSender(), cmd);

                            try (PreparedStatement delStmt = conn.prepareStatement("DELETE FROM pending_commands WHERE id = ?")) {
                                delStmt.setInt(1, id);
                                delStmt.executeUpdate();
                            }
                        }
                    }
                } catch (SQLException e) {
                    e.printStackTrace();
                }
            }
        }.runTaskTimer(this, 20L, 20L);
    }

    @Override
    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player)) {
            sender.sendMessage("Эту команду может выполнять только игрок!");
            return true;
        }

        Player player = (Player) sender;
        String code = String.format("%06d", new SecureRandom().nextInt(1000000));
        int expirationSeconds = getConfig().getInt("code-expiration-seconds", 300);
        long expiresAt = (System.currentTimeMillis() / 1000) + expirationSeconds;

        try {
            Connection conn = getConnection();
            String sql = "INSERT INTO pending_codes (code, uuid, expires_at) VALUES (?, ?, ?) ON CONFLICT (code) DO UPDATE SET uuid = EXCLUDED.uuid, expires_at = EXCLUDED.expires_at";
            try (PreparedStatement pstmt = conn.prepareStatement(sql)) {
                pstmt.setString(1, code);
                pstmt.setString(2, player.getUniqueId().toString());
                pstmt.setLong(3, expiresAt);
                pstmt.executeUpdate();
            }

            String msgGenerated = getConfig().getString("messages.code-generated", "&aВаш код привязки Telegram: &e&l%code%").replace("%code%", code);
            String msgInstructions = getConfig().getString("messages.code-instructions", "&eОтправьте эти 6 цифр боту в Telegram.");

            player.sendMessage(ChatColor.translateAlternateColorCodes('&', msgGenerated));
            player.sendMessage(ChatColor.translateAlternateColorCodes('&', msgInstructions));

        } catch (SQLException e) {
            player.sendMessage(ChatColor.RED + "Произошла ошибка при генерации кода.");
            e.printStackTrace();
        }

        return true;
    }
}